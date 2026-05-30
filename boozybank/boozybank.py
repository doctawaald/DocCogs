import asyncio
import time
import random
import json
import logging
import aiohttp
import discord
from redbot.core import Config, commands, bank
from redbot.core.utils.chat_formatting import box

log = logging.getLogger("red.boozybank")

class BoozyBank(commands.Cog):
    """AI-Powered Trivia Game that deposits coins in the Redbot bank."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=892347891234, force_registration=True)

        default_guild = {
            "quiz_reward": 100,
            "timeout": 30,
            "show_explanation": True,
            "model": "gpt-4o-mini",
            "allow_second_guess": False,
            "max_game_payout": 1000,
            "easy_endreward": 100,
            "medium_endreward": 200,
            "hard_endreward": 400,
            "cleanup_messages": True,
            "final_cleanup_delay": 5, # default 5 minutes, 0 to disable
            "default_topics": [
                "Beer & Breweries",
                "Classic Cocktails",
                "General Knowledge",
                "World History",
                "Pop Culture & Movies",
                "Video Games",
                "Science & Nature",
                "Music Hits",
                "Geography & Landmarks"
            ]
        }

        default_member = {
            "wins": 0,
            "earnings": 0
        }

        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)

        # Active channel quizzes lock
        self.active_quizzes = set()
        self.running_tasks = {} # {channel_id: asyncio.Task}

    def _get_speed_multiplier(self, elapsed: float) -> tuple:
        """Returns the multiplier and a custom speed tier name based on response speed."""
        if elapsed <= 2.00:
            return 1.50, "⚡ Lightning Speed! (Under 2.00s)"
        elif elapsed <= 5.00:
            return 1.20, "🚀 Quick Speed! (Under 5.00s)"
        else:
            return 1.00, "🐢 Standard Speed (Over 5.00s)"

    async def _cleanup_round_messages(self, ctx, question_msg, player_msgs):
        """Safely bulk-deletes question embeds and player guesses to keep the channel clean."""
        try:
            if not await self.config.guild(ctx.guild).cleanup_messages():
                return
        except Exception:
            return

        # 1. Delete question message
        if question_msg:
            try:
                await question_msg.delete()
            except discord.HTTPException:
                pass

        # 2. Bulk delete player guess messages
        if player_msgs:
            permissions = ctx.channel.permissions_for(ctx.me)
            if permissions.manage_messages:
                try:
                    await ctx.channel.delete_messages(player_msgs)
                except discord.HTTPException:
                    # Fallback to individual delete if bulk fails
                    for m in player_msgs:
                        try:
                            await m.delete()
                        except discord.HTTPException:
                            pass
            else:
                pass

    async def _add_reactions_background(self, ctx, message, emojis):
        """Asynchronously adds emoji buttons in the background so the round starts instantly."""
        for emoji in emojis:
            try:
                await message.add_reaction(emoji)
            except discord.Forbidden:
                log.warning(f"Missing 'Add Reactions' permission in guild {ctx.guild.name} (channel: {ctx.channel.name}). Emoji buttons could not be added.")
                break
            except discord.HTTPException:
                pass

    def _schedule_final_cleanup(self, guild: discord.Guild, message: discord.Message):
        """Schedules a non-blocking background task to delete a final result embed after the configured delay."""
        async def do_cleanup():
            try:
                delay_minutes = await self.config.guild(guild).final_cleanup_delay()
                if delay_minutes <= 0:
                    return
                await asyncio.sleep(delay_minutes * 60)
                await message.delete()
            except discord.HTTPException:
                pass # Already deleted or missing permissions
            except Exception as e:
                log.error(f"Error during final cleanup: {e}")

        if message:
            asyncio.create_task(do_cleanup())

    async def _generate_quiz(self, guild: discord.Guild, topic: str, difficulty: str) -> dict:
        """Fetches a single quiz question from OpenAI via a non-blocking request."""
        tokens = await self.bot.get_shared_api_tokens("openai")
        api_key = tokens.get("api_key")
        if not api_key:
            raise ValueError(
                "De OpenAI API-key is nog niet ingesteld!\n"
                "Gebruik het commando `[p]set api openai api_key,<api_key>` om deze in te stellen."
            )

        model = await self.config.guild(guild).model()

        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        system_prompt = (
            "You are a professional trivia and quiz generator.\n"
            "Your task is to generate a single, highly engaging, accurate multiple-choice question.\n"
            "You MUST return the output as a valid JSON object. "
            "Do not wrap it in markdown code blocks like ```json ... ```. Just return the raw JSON string.\n"
            "The JSON object must have exactly the following structure:\n"
            "{\n"
            "  \"question\": \"The trivia question text\",\n"
            "  \"options\": {\n"
            "    \"A\": \"Option A content\",\n"
            "    \"B\": \"Option B content\",\n"
            "    \"C\": \"Option C content\",\n"
            "    \"D\": \"Option D content\"\n"
            "  },\n"
            "  \"correct_answer\": \"A\", // MUST be 'A', 'B', 'C', or 'D'\n"
            "  \"explanation\": \"A short, fun explanation of why this answer is correct.\"\n"
            "}"
        )

        user_prompt = (
            f"Generate an engaging multiple-choice trivia question in English about the topic '{topic}'.\n"
            f"Difficulty level: {difficulty}.\n"
            f"Ensure all choices are realistic but with only one objectively correct answer."
        )

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.8
        }

        session = getattr(self.bot, "session", None)
        if session is None or session.closed:
            async with aiohttp.ClientSession() as temp_session:
                async with temp_session.post(url, headers=headers, json=payload, timeout=20) as response:
                    if response.status != 200:
                        text = await response.text()
                        raise RuntimeError(f"OpenAI API returned status {response.status}: {text}")
                    data = await response.json()
        else:
            async with session.post(url, headers=headers, json=payload, timeout=20) as response:
                if response.status != 200:
                    text = await response.text()
                    raise RuntimeError(f"OpenAI API returned status {response.status}: {text}")
                data = await response.json()

        try:
            content = data["choices"][0]["message"]["content"]
            quiz_data = json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise RuntimeError(f"Could not parse the OpenAI response. Error: {e}")

        # Validate quiz data structure
        required_keys = ["question", "options", "correct_answer", "explanation"]
        for key in required_keys:
            if key not in quiz_data:
                raise KeyError(f"Missing key '{key}' in OpenAI response.")

        if not isinstance(quiz_data["options"], dict) or len(quiz_data["options"]) != 4:
            raise ValueError("Options must be a dictionary with exactly 4 choices (A, B, C, D).")

        ans = quiz_data["correct_answer"].strip().upper()
        if ans not in ["A", "B", "C", "D"]:
            raise ValueError(f"Correct answer '{ans}' is not A, B, C, or D.")

        standard_options = {}
        for letter in ["A", "B", "C", "D"]:
            val = None
            for k, v in quiz_data["options"].items():
                if k.upper() == letter:
                    val = v
                    break
            if val is None:
                raise ValueError(f"Missing option '{letter}' in the options.")
            standard_options[letter] = val

        quiz_data["options"] = standard_options
        quiz_data["correct_answer"] = ans
        return quiz_data

    async def _generate_quiz_batch(self, guild: discord.Guild, topic: str, difficulty: str, rounds: int) -> list:
        """Fetches a batch of quiz questions from OpenAI in a single JSON API call."""
        tokens = await self.bot.get_shared_api_tokens("openai")
        api_key = tokens.get("api_key")
        if not api_key:
            raise ValueError(
                "The OpenAI API key has not been configured yet!\n"
                "Use the command `[p]set api openai api_key,<api_key>` to set it."
            )

        model = await self.config.guild(guild).model()

        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        system_prompt = (
            "You are a professional trivia and quiz generator.\n"
            "Your task is to generate a list of highly engaging, accurate multiple-choice questions.\n"
            "You MUST return the output as a valid JSON object containing an array under the key 'questions'. "
            "Do not wrap it in markdown code blocks like ```json ... ```. Just return the raw JSON string.\n"
            "The JSON object must have exactly the following structure:\n"
            "{\n"
            "  \"questions\": [\n"
            "    {\n"
            "      \"question\": \"The trivia question text\",\n"
            "      \"options\": {\n"
            "        \"A\": \"Option A content\",\n"
            "        \"B\": \"Option B content\",\n"
            "        \"C\": \"Option C content\",\n"
            "        \"D\": \"Option D content\"\n"
            "      },\n"
            "      \"correct_answer\": \"A\", // MUST be 'A', 'B', 'C', or 'D'\n"
            "      \"explanation\": \"A short, fun explanation of why this answer is correct.\"\n"
            "    }\n"
            "  ]\n"
            "}"
        )

        user_prompt = (
            f"Generate a list of {rounds} unique multiple-choice trivia questions in English about the topic '{topic}'.\n"
            f"Difficulty level: {difficulty}.\n"
            f"Ensure all choices are realistic but with only one objectively correct answer."
        )

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.8
        }

        session = getattr(self.bot, "session", None)
        if session is None or session.closed:
            async with aiohttp.ClientSession() as temp_session:
                async with temp_session.post(url, headers=headers, json=payload, timeout=30) as response:
                    if response.status != 200:
                        text = await response.text()
                        raise RuntimeError(f"OpenAI API returned status {response.status}: {text}")
                    data = await response.json()
        else:
            async with session.post(url, headers=headers, json=payload, timeout=30) as response:
                if response.status != 200:
                    text = await response.text()
                    raise RuntimeError(f"OpenAI API returned status {response.status}: {text}")
                data = await response.json()

        try:
            content = data["choices"][0]["message"]["content"]
            batch_data = json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise RuntimeError(f"Could not parse the OpenAI response. Error: {e}")

        if "questions" not in batch_data or not isinstance(batch_data["questions"], list):
            raise KeyError("Missing or invalid 'questions' array in OpenAI response.")

        clean_questions = []
        for index, quiz in enumerate(batch_data["questions"]):
            required_keys = ["question", "options", "correct_answer", "explanation"]
            for key in required_keys:
                if key not in quiz:
                    raise KeyError(f"Question #{index+1} is missing key '{key}'.")

            if not isinstance(quiz["options"], dict) or len(quiz["options"]) != 4:
                raise ValueError(f"Question #{index+1} options are not exactly 4 choices (A, B, C, D).")

            ans = quiz["correct_answer"].strip().upper()
            if ans not in ["A", "B", "C", "D"]:
                raise ValueError(f"Question #{index+1} correct answer '{ans}' is not A, B, C, or D.")

            standard_options = {}
            for letter in ["A", "B", "C", "D"]:
                val = None
                for k, v in quiz["options"].items():
                    if k.upper() == letter:
                        val = v
                        break
                if val is None:
                    raise ValueError(f"Question #{index+1} is missing option '{letter}'.")
                standard_options[letter] = val

            quiz["options"] = standard_options
            quiz["correct_answer"] = ans
            clean_questions.append(quiz)

        return clean_questions

    @commands.command()
    @commands.guild_only()
    async def boozyquiz(self, ctx, *, topic_and_difficulty: str = None):
        """Start a single AI-generated multiple-choice quiz.

        You can optionally specify a topic and/or difficulty.
        If no topic is specified, a random default topic is chosen.
        Difficulties: easy, medium, hard (default is medium).

        Examples:
        `[p]boozyquiz`
        `[p]boozyquiz cocktails`
        `[p]boozyquiz history hard`
        `[p]boozyquiz Video Games easy`
        """
        channel = ctx.channel

        if channel.id in self.active_quizzes:
            await ctx.send("🍻 A quiz is already active in this channel! Solve that one first.")
            return

        topic = None
        difficulty = "medium"

        if topic_and_difficulty:
            words = topic_and_difficulty.strip().split()
            if words[0].lower() in ["easy", "medium", "hard"]:
                difficulty = words[0].lower()
                topic = " ".join(words[1:]).strip() if len(words) > 1 else None
            elif words[-1].lower() in ["easy", "medium", "hard"]:
                difficulty = words[-1].lower()
                topic = " ".join(words[:-1]).strip() if len(words) > 1 else None
            else:
                topic = topic_and_difficulty.strip()

        if not topic:
            default_topics = await self.config.guild(ctx.guild).default_topics()
            topic = random.choice(default_topics) if default_topics else "General Knowledge"

        self.active_quizzes.add(channel.id)
        self.running_tasks[channel.id] = asyncio.current_task()

        emoji_beer = "🍻"
        generating_msg = await ctx.send(
            f"{emoji_beer} Generating an **{difficulty}** quiz question about **{topic}** via OpenAI... Please wait!"
        )

        try:
            quiz_data = await self._generate_quiz(ctx.guild, topic, difficulty)
        except Exception as e:
            self.active_quizzes.discard(channel.id)
            self.running_tasks.pop(channel.id, None)
            await generating_msg.delete()
            log.error(f"Error generating quiz: {e}", exc_info=True)
            await ctx.send(f"❌ An error occurred while retrieving the quiz:\n{e}")
            return

        await generating_msg.delete()

        question = quiz_data["question"]
        options = quiz_data["options"]
        correct_answer = quiz_data["correct_answer"]
        explanation = quiz_data["explanation"]

        choices_str = ""
        for letter, opt in options.items():
            choices_str += f"**{letter}**: {opt}\n"

        emb = discord.Embed(
            title=f"🍻 BoozyBank Trivia! 🍻",
            color=discord.Color.gold(),
            description=f"**Topic:** {topic} | **Difficulty:** {difficulty.capitalize()}\n\n"
                        f"**QUESTION:**\n{question}\n\n"
                        f"**CHOICES:**\n{choices_str}"
        )

        timeout = await self.config.guild(ctx.guild).timeout()
        allow_second_guess = await self.config.guild(ctx.guild).allow_second_guess()
        currency_name = await bank.get_currency_name(ctx.guild)

        emb.set_footer(text=f"Click a button below or type A, B, C, D! | Time limit: {timeout}s")

        question_msg = await ctx.send(embed=emb)

        # Add emoji buttons in the background so the round timer starts instantly!
        emoji_buttons = ["🇦", "🇧", "🇨", "🇩"]
        emoji_to_letter = {"🇦": "A", "🇧": "B", "🇨": "C", "🇩": "D"}
        asyncio.create_task(self._add_reactions_background(ctx, question_msg, emoji_buttons))

        answered_users = set()
        player_msgs = []
        start_time = time.time()
        winner = None
        elapsed = 0.0

        def check_msg(m):
            if m.channel.id != ctx.channel.id:
                return False
            if m.author.bot:
                return False
            ans_attempt = m.content.strip().upper()
            if ans_attempt not in ["A", "B", "C", "D"]:
                return False
            if not allow_second_guess and m.author.id in answered_users:
                return False
            return True

        def check_rxn(reaction, user):
            if reaction.message.id != question_msg.id:
                return False
            if user.bot:
                return False
            emoji_str = str(reaction.emoji)
            if emoji_str not in emoji_buttons:
                return False
            if not allow_second_guess and user.id in answered_users:
                return False
            return True

        try:
            while time.time() - start_time < timeout:
                remaining = timeout - (time.time() - start_time)
                if remaining <= 0:
                    break

                # Concurrent wait tasks
                msg_task = asyncio.create_task(self.bot.wait_for("message", check=check_msg, timeout=remaining))
                rxn_task = asyncio.create_task(self.bot.wait_for("reaction_add", check=check_rxn, timeout=remaining))

                done, pending = await asyncio.wait(
                    [msg_task, rxn_task],
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=remaining
                )

                for t in pending:
                    t.cancel()

                answered_user = None
                ans_attempt = None
                trigger_msg = None
                trigger_rxn = None

                for completed in done:
                    try:
                        result = completed.result()
                        if isinstance(result, discord.Message):
                            trigger_msg = result
                            answered_user = result.author
                            ans_attempt = result.content.strip().upper()
                            player_msgs.append(result)
                        else:
                            reaction, user = result
                            trigger_rxn = reaction
                            answered_user = user
                            ans_attempt = emoji_to_letter[str(reaction.emoji)]
                    except Exception:
                        pass

                if not answered_user or not ans_attempt:
                    break

                answered_users.add(answered_user.id)

                if ans_attempt == correct_answer:
                    winner = answered_user
                    elapsed = time.time() - start_time
                    if trigger_msg:
                        try:
                            await trigger_msg.add_reaction("✅")
                        except discord.HTTPException:
                            pass
                    break
                else:
                    if trigger_msg:
                        try:
                            await trigger_msg.add_reaction("❌")
                        except discord.HTTPException:
                            pass
                    elif trigger_rxn:
                        # Auto-remove player's wrong reaction emoji button
                        permissions = ctx.channel.permissions_for(ctx.me)
                        if permissions.manage_messages:
                            try:
                                await question_msg.remove_reaction(trigger_rxn.emoji, answered_user)
                            except discord.HTTPException:
                                pass

        except asyncio.CancelledError:
            self.active_quizzes.discard(channel.id)
            self.running_tasks.pop(channel.id, None)
            raise

        self.active_quizzes.discard(channel.id)
        self.running_tasks.pop(channel.id, None)

        # Cleanup round messages
        await self._cleanup_round_messages(ctx, question_msg, player_msgs)

        if winner:
            base_reward = await self.config.guild(ctx.guild).quiz_reward()
            
            # Apply reflex multiplier
            multiplier, speed_tier = self._get_speed_multiplier(elapsed)
            reward = int(base_reward * multiplier)

            deposit_success = True
            max_bal = 0
            try:
                await bank.deposit_credits(winner, reward)
            except bank.errors.BalanceTooHigh:
                deposit_success = False
                max_bal = await bank.get_max_balance(ctx.guild)

            # Update database
            current_wins = await self.config.member(winner).wins()
            current_earnings = await self.config.member(winner).earnings()
            await self.config.member(winner).wins.set(current_wins + 1)
            await self.config.member(winner).earnings.set(current_earnings + reward)

            winner_emb = discord.Embed(
                title="🎉 We have a winner! 🎉",
                color=discord.Color.green(),
                description=f"Congratulations {winner.mention}! You answered correctly!\n\n"
                            f"**Question:** {question}\n"
                            f"**Correct Answer:** **{correct_answer}** ({options[correct_answer]})\n\n"
                            f"⏱️ **Speed:** `{elapsed:.2f}` seconds\n"
                            f"⚡ **Speed Rank:** {speed_tier}\n"
                            f"💰 **Reward:** `{reward}` {currency_name} *(Multiplier: {multiplier}x)*"
            )

            if not deposit_success:
                winner_emb.add_field(
                    name="⚠️ Wallet Full",
                    value=f"You did not receive your reward because your bank account has reached the limit of `{max_bal}` {currency_name}!",
                    inline=False
                )

            show_explanation = await self.config.guild(ctx.guild).show_explanation()
            if show_explanation and explanation:
                winner_emb.add_field(
                    name="ℹ️ Explanation",
                    value=explanation,
                    inline=False
                )

            avatar_url = winner.display_avatar.url if hasattr(winner, "display_avatar") else winner.avatar_url
            winner_emb.set_thumbnail(url=avatar_url)
            
            final_msg = await ctx.send(embed=winner_emb)
            self._schedule_final_cleanup(ctx.guild, final_msg)

        else:
            timeout_emb = discord.Embed(
                title="⏰ Time is up!",
                color=discord.Color.red(),
                description=f"Nobody guessed the correct answer in time!\n\n"
                            f"**Question:** {question}\n"
                            f"**Correct Answer:** **{correct_answer}** ({options[correct_answer]})"
            )

            show_explanation = await self.config.guild(ctx.guild).show_explanation()
            if show_explanation and explanation:
                timeout_emb.add_field(
                    name="ℹ️ Explanation",
                    value=explanation,
                    inline=False
                )

            final_msg = await ctx.send(embed=timeout_emb)
            self._schedule_final_cleanup(ctx.guild, final_msg)

    @commands.command()
    @commands.guild_only()
    async def boozygame(self, ctx, rounds: int = 5, *, topic_and_difficulty: str = None):
        """Start a multi-round fast-paced trivia game!

        All questions are pre-generated in a single API call to keep the game incredibly fast-paced with zero delays.
        Individual rounds award scoreboard points, and overall game winner(s) receive the End Game Reward!

        Parameters:
        `rounds`: Number of rounds to play (between 1 and 10, default is 5).
        `topic_and_difficulty`: Optional custom topic and/or difficulty.

        Example:
        `[p]boozygame 5 Pop Culture hard`
        """
        channel = ctx.channel

        if rounds < 1 or rounds > 10:
            await ctx.send("❌ Number of rounds must be between 1 and 10.")
            return

        if channel.id in self.active_quizzes:
            await ctx.send("🍻 A game or quiz is already active in this channel! Solve that one first.")
            return

        topic = None
        difficulty = "medium"

        if topic_and_difficulty:
            words = topic_and_difficulty.strip().split()
            if words[0].lower() in ["easy", "medium", "hard"]:
                difficulty = words[0].lower()
                topic = " ".join(words[1:]).strip() if len(words) > 1 else None
            elif words[-1].lower() in ["easy", "medium", "hard"]:
                difficulty = words[-1].lower()
                topic = " ".join(words[:-1]).strip() if len(words) > 1 else None
            else:
                topic = topic_and_difficulty.strip()

        if not topic:
            default_topics = await self.config.guild(ctx.guild).default_topics()
            topic = random.choice(default_topics) if default_topics else "General Knowledge"

        self.active_quizzes.add(channel.id)
        self.running_tasks[channel.id] = asyncio.current_task()

        generating_msg = await ctx.send(
            f"🍻 Preparing a **{rounds}-round** fast-paced game about **{topic}** ({difficulty})...\n"
            f"Fetching all questions in advance for a lightning-fast experience! Please wait..."
        )

        try:
            questions = await self._generate_quiz_batch(ctx.guild, topic, difficulty, rounds)
        except Exception as e:
            self.active_quizzes.discard(channel.id)
            self.running_tasks.pop(channel.id, None)
            await generating_msg.delete()
            log.error(f"Error batch-generating quiz game: {e}", exc_info=True)
            await ctx.send(f"❌ Failed to load the trivia game: {e}")
            return

        await generating_msg.delete()

        game_scores = {} # Scoreboard points: {Member: total_points}
        game_wins = {} # Scoreboard rounds won: {Member: correct_answers_count}
        game_speeds = {} # Speed tracking: {Member: [speeds_list]}
        game_multipliers = {} # Multiplier tracking: {Member: [multipliers_list]}
        currency_name = await bank.get_currency_name(ctx.guild)
        
        timeout = await self.config.guild(ctx.guild).timeout()
        allow_second_guess = await self.config.guild(ctx.guild).allow_second_guess()
        show_explanation = await self.config.guild(ctx.guild).show_explanation()

        await ctx.send(
            f"🎉 **BoozyGame Started!** 🎉\n"
            f"**Topic:** {topic} | **Difficulty:** {difficulty.capitalize()} | **Rounds:** {rounds}\n"
            f"Get ready, Round 1 is starting in 3 seconds..."
        )
        await asyncio.sleep(3.0)

        emoji_buttons = ["🇦", "🇧", "🇨", "🇩"]
        emoji_to_letter = {"🇦": "A", "🇧": "B", "🇨": "C", "🇩": "D"}

        try:
            for index, quiz in enumerate(questions, start=1):
                if channel.id not in self.active_quizzes:
                    break

                question = quiz["question"]
                options = quiz["options"]
                correct_answer = quiz["correct_answer"]
                explanation = quiz["explanation"]

                choices_str = ""
                for letter, opt in options.items():
                    choices_str += f"**{letter}**: {opt}\n"

                emb = discord.Embed(
                    title=f"🍻 BoozyGame - Round {index} of {rounds} 🍻",
                    color=discord.Color.orange(),
                    description=f"**QUESTION:**\n{question}\n\n**CHOICES:**\n{choices_str}"
                )
                emb.set_footer(text=f"Click a button below or type A, B, C, D! | Round limit: {timeout}s")
                
                round_msg = await ctx.send(embed=emb)

                # Add emoji buttons in the background so the round timer starts instantly!
                asyncio.create_task(self._add_reactions_background(ctx, round_msg, emoji_buttons))

                answered_users = set()
                player_msgs = []
                start_time = time.time()
                winner = None
                elapsed = 0.0

                def check_msg(m):
                    if m.channel.id != ctx.channel.id:
                        return False
                    if m.author.bot:
                        return False
                    ans_attempt = m.content.strip().upper()
                    if ans_attempt not in ["A", "B", "C", "D"]:
                        return False
                    if not allow_second_guess and m.author.id in answered_users:
                        return False
                    return True

                def check_rxn(reaction, user):
                    if reaction.message.id != round_msg.id:
                        return False
                    if user.bot:
                        return False
                    emoji_str = str(reaction.emoji)
                    if emoji_str not in emoji_buttons:
                        return False
                    if not allow_second_guess and user.id in answered_users:
                        return False
                    return True

                while time.time() - start_time < timeout:
                    remaining = timeout - (time.time() - start_time)
                    if remaining <= 0:
                        break

                    # Concurrent message/reaction wait
                    msg_task = asyncio.create_task(self.bot.wait_for("message", check=check_msg, timeout=remaining))
                    rxn_task = asyncio.create_task(self.bot.wait_for("reaction_add", check=check_rxn, timeout=remaining))

                    done, pending = await asyncio.wait(
                        [msg_task, rxn_task],
                        return_when=asyncio.FIRST_COMPLETED,
                        timeout=remaining
                    )

                    for t in pending:
                        t.cancel()

                    answered_user = None
                    ans_attempt = None
                    trigger_msg = None
                    trigger_rxn = None

                    for completed in done:
                        try:
                            result = completed.result()
                            if isinstance(result, discord.Message):
                                trigger_msg = result
                                answered_user = result.author
                                ans_attempt = result.content.strip().upper()
                                player_msgs.append(result)
                            else:
                                reaction, user = result
                                trigger_rxn = reaction
                                answered_user = user
                                ans_attempt = emoji_to_letter[str(reaction.emoji)]
                        except Exception:
                            pass

                    if not answered_user or not ans_attempt:
                        break

                    answered_users.add(answered_user.id)

                    if ans_attempt == correct_answer:
                        winner = answered_user
                        elapsed = time.time() - start_time
                        if trigger_msg:
                            try:
                                await trigger_msg.add_reaction("✅")
                            except discord.HTTPException:
                                pass
                        break
                    else:
                        if trigger_msg:
                            try:
                                await trigger_msg.add_reaction("❌")
                            except discord.HTTPException:
                                pass
                        elif trigger_rxn:
                            # Auto-remove player's wrong reaction emoji button
                            permissions = ctx.channel.permissions_for(ctx.me)
                            if permissions.manage_messages:
                                try:
                                    await round_msg.remove_reaction(trigger_rxn.emoji, answered_user)
                                except discord.HTTPException:
                                    pass

                # Round message cleanup
                await self._cleanup_round_messages(ctx, round_msg, player_msgs)

                if winner:
                    multiplier, speed_tier = self._get_speed_multiplier(elapsed)
                    points_earned = int(100 * multiplier)
                    
                    # Track score and stats
                    game_scores[winner] = game_scores.get(winner, 0) + points_earned
                    game_wins[winner] = game_wins.get(winner, 0) + 1
                    game_speeds.setdefault(winner, []).append(elapsed)
                    game_multipliers.setdefault(winner, []).append(multiplier)

                    round_win_emb = discord.Embed(
                        title=f"🎯 Round {index} Won!",
                        color=discord.Color.green(),
                        description=f"{winner.mention} got it right! Answer was **{correct_answer}** ({options[correct_answer]})\n\n"
                                    f"⏱️ **Speed:** `{elapsed:.2f}` seconds\n"
                                    f"⚡ **Speed Rank:** {speed_tier}\n"
                                    f"🎯 **Points Awarded:** `+{points_earned}` points *(Base: 100 x {multiplier:.2f}x)*\n"
                                    f"📊 *Score updated! Check the leaderboard at the end.*"
                    )
                    if show_explanation and explanation:
                        round_win_emb.add_field(name="ℹ️ Explanation", value=explanation, inline=False)
                    
                    round_final_msg = await ctx.send(embed=round_win_emb)
                    self._schedule_final_cleanup(ctx.guild, round_final_msg)
                else:
                    round_timeout_emb = discord.Embed(
                        title=f"⏰ Round {index} - Time is up!",
                        color=discord.Color.red(),
                        description=f"Nobody guessed correctly in time!\n\n"
                                    f"**Correct Answer:** **{correct_answer}** ({options[correct_answer]})"
                    )
                    if show_explanation and explanation:
                        round_timeout_emb.add_field(name="ℹ️ Explanation", value=explanation, inline=False)
                    
                    round_final_msg = await ctx.send(embed=round_timeout_emb)
                    self._schedule_final_cleanup(ctx.guild, round_final_msg)

                if index < rounds:
                    await ctx.send(f"Round {index+1} is starting in 5 seconds...")
                    await asyncio.sleep(5.0)

        except asyncio.CancelledError:
            self.active_quizzes.discard(channel.id)
            self.running_tasks.pop(channel.id, None)
            raise

        if not game_scores:
            self.active_quizzes.discard(channel.id)
            self.running_tasks.pop(channel.id, None)
            await ctx.send("🏁 **Game Over!** Nobody won any rounds, so no coins will be distributed.")
            return

        # Find top score and check for TIE
        sorted_scores = sorted(game_scores.items(), key=lambda x: x[1], reverse=True)
        max_score = sorted_scores[0][1]
        grand_winners = [member for member, score in sorted_scores if score == max_score]

        # ⚔️ SUDDEN DEATH TIE-BREAKER ⚔️
        tie_broken = False
        tie_breaker_attempts = 0
        max_tie_breakers = 3

        if len(grand_winners) > 1:
            champs_mentions = ", ".join(c.mention for c in grand_winners)
            await ctx.send(
                f"⚔️ **SUDDEN DEATH TIE-BREAKER!** ⚔️\n"
                f"We have a tie! {champs_mentions} both finished with **{max_score} points**!\n"
                f"I will generate tie-breaker questions. **Only** these players can answer! Get ready..."
            )
            await asyncio.sleep(4.0)

            while len(grand_winners) > 1 and tie_breaker_attempts < max_tie_breakers:
                tie_breaker_attempts += 1
                await ctx.send(f"Generating Tie-Breaker Question #{tie_breaker_attempts}...")

                try:
                    tb_quiz = await self._generate_quiz(ctx.guild, topic, difficulty)
                except Exception as e:
                    log.error(f"Error generating tie breaker question: {e}")
                    await ctx.send("❌ Failed to generate tie-breaker. Skipping to final draw.")
                    break

                tb_question = tb_quiz["question"]
                tb_options = tb_quiz["options"]
                tb_correct = tb_quiz["correct_answer"]
                tb_explanation = tb_quiz["explanation"]

                tb_choices = ""
                for letter, opt in tb_options.items():
                    tb_choices += f"**{letter}**: {opt}\n"

                tb_emb = discord.Embed(
                    title=f"⚔️ Tie-Breaker Round {tie_breaker_attempts} ⚔️",
                    color=discord.Color.red(),
                    description=f"**ONLY TIE CONTENDERS CAN ANSWER!**\n\n"
                                f"**QUESTION:**\n{tb_question}\n\n**CHOICES:**\n{tb_choices}"
                )
                tb_emb.set_footer(text=f"Tied players: Tap a button or type A, B, C, D! | Time: {timeout}s")

                tb_msg = await ctx.send(embed=tb_emb)
                asyncio.create_task(self._add_reactions_background(ctx, tb_msg, emoji_buttons))

                answered_users = set()
                tb_player_msgs = []
                tb_start = time.time()
                tb_winner = None
                tb_elapsed = 0.0

                def check_tb_msg(m):
                    if m.channel.id != ctx.channel.id:
                        return False
                    if m.author not in grand_winners:
                        return False
                    ans_attempt = m.content.strip().upper()
                    if ans_attempt not in ["A", "B", "C", "D"]:
                        return False
                    if not allow_second_guess and m.author.id in answered_users:
                        return False
                    return True

                def check_tb_rxn(reaction, user):
                    if reaction.message.id != tb_msg.id:
                        return False
                    if user not in grand_winners:
                        return False
                    emoji_str = str(reaction.emoji)
                    if emoji_str not in emoji_buttons:
                        return False
                    if not allow_second_guess and user.id in answered_users:
                        return False
                    return True

                while time.time() - tb_start < timeout:
                    rem = timeout - (time.time() - tb_start)
                    if rem <= 0:
                        break

                    m_task = asyncio.create_task(self.bot.wait_for("message", check=check_tb_msg, timeout=rem))
                    r_task = asyncio.create_task(self.bot.wait_for("reaction_add", check=check_tb_rxn, timeout=rem))

                    d, p = await asyncio.wait([m_task, r_task], return_when=asyncio.FIRST_COMPLETED, timeout=rem)
                    for pending_t in p:
                        pending_t.cancel()

                    ans_user = None
                    ans_val = None
                    trig_m = None
                    trig_r = None

                    for comp in d:
                        try:
                            res = comp.result()
                            if isinstance(res, discord.Message):
                                trig_m = res
                                ans_user = res.author
                                ans_val = res.content.strip().upper()
                                tb_player_msgs.append(res)
                            else:
                                rxn, u = res
                                trig_r = rxn
                                ans_user = u
                                ans_val = emoji_to_letter[str(rxn.emoji)]
                        except Exception:
                            pass

                    if not ans_user or not ans_val:
                        break

                    answered_users.add(ans_user.id)

                    if ans_val == tb_correct:
                        tb_winner = ans_user
                        tb_elapsed = time.time() - tb_start
                        if trig_m:
                            try:
                                await trig_m.add_reaction("✅")
                            except discord.HTTPException:
                                pass
                        break
                    else:
                        if trig_m:
                            try:
                                await trig_m.add_reaction("❌")
                            except discord.HTTPException:
                                pass
                        elif trig_r:
                            perm = ctx.channel.permissions_for(ctx.me)
                            if perm.manage_messages:
                                try:
                                    await tb_msg.remove_reaction(trig_r.emoji, ans_user)
                                except discord.HTTPException:
                                    pass

                # Cleanup tie-breaker messages
                await self._cleanup_round_messages(ctx, tb_msg, tb_player_msgs)

                if tb_winner:
                    grand_winners = [tb_winner] # Tie successfully broken!
                    tie_broken = True
                    
                    # Log final tie win stats
                    multiplier, speed_tier = self._get_speed_multiplier(tb_elapsed)
                    points_earned = int(100 * multiplier)
                    game_scores[tb_winner] = game_scores.get(tb_winner, 0) + points_earned
                    game_wins[tb_winner] = game_wins.get(tb_winner, 0) + 1
                    game_speeds.setdefault(tb_winner, []).append(tb_elapsed)
                    game_multipliers.setdefault(tb_winner, []).append(multiplier)

                    tb_win_emb = discord.Embed(
                        title="🎯 Tie-Breaker Solved!",
                        color=discord.Color.green(),
                        description=f"{tb_winner.mention} answered correctly and broke the tie! Answer was **{tb_correct}** ({tb_options[tb_correct]})\n\n"
                                    f"⏱️ **Speed:** `{tb_elapsed:.2f}` seconds (Multiplier: {multiplier}x)\n"
                                    f"👑 Crowned overall Champion!"
                    )
                    if show_explanation and tb_explanation:
                        tb_win_emb.add_field(name="ℹ️ Explanation", value=tb_explanation, inline=False)
                    
                    tb_final = await ctx.send(embed=tb_win_emb)
                    self._schedule_final_cleanup(ctx.guild, tb_final)
                    break
                else:
                    await ctx.send("❌ Tie-breaker timed out or had no correct answers.")
                    if tie_breaker_attempts < max_tie_breakers:
                        await asyncio.sleep(3.0)

            if not tie_broken:
                await ctx.send("🏳️ All tie-breaker attempts failed! We declare a shared draw.")

        self.active_quizzes.discard(channel.id)
        self.running_tasks.pop(channel.id, None)

        # Final end reward distribution
        end_reward_key = f"{difficulty}_endreward"
        base_end_reward = await self.config.guild(ctx.guild).get_attr(end_reward_key)()

        payout_results = {}
        champions_list = grand_winners # Can be multiple if draw occurred

        # Calculate flat payouts for the champions (divided equally for draws)
        payouts_by_winner = {}
        total_payout_requested = 0
        num_champs = len(champions_list)

        for champ in champions_list:
            final_payout = int(base_end_reward / num_champs)
            payouts_by_winner[champ] = final_payout
            total_payout_requested += final_payout

        # Safety Cap
        max_game_payout = await self.config.guild(ctx.guild).max_game_payout()
        scaling_factor = 1.0
        if total_payout_requested > max_game_payout:
            scaling_factor = max_game_payout / total_payout_requested

        # Distribute coins and save to database
        for champ in champions_list:
            unscaled_payout = payouts_by_winner[champ]
            final_coins = int(unscaled_payout * scaling_factor)
            payout_results[champ] = final_coins

            try:
                await bank.deposit_credits(champ, final_coins)
            except bank.errors.BalanceTooHigh:
                pass

        # Update stats
        for player, score in game_scores.items():
            current_wins = await self.config.member(player).wins()
            current_earnings = await self.config.member(player).earnings()
            
            winnings_won = payout_results.get(player, 0)
            rounds_won_count = game_wins.get(player, 0)
            await self.config.member(player).wins.set(current_wins + rounds_won_count)
            await self.config.member(player).earnings.set(current_earnings + winnings_won)

        # Re-sort final scores for podium
        final_scores = sorted(game_scores.items(), key=lambda x: x[1], reverse=True)

        # Final embed
        podium_emb = discord.Embed(
            title="🏁 Trivia Game Over! Final Scores 🏁",
            color=discord.Color.gold(),
            description=f"**Topic:** {topic} | **Difficulty:** {difficulty.capitalize()}\n"
                        f"Overall match winners receive the End Game Reward:\n\n"
        )

        podium_text = ""
        for rank, (player, score) in enumerate(final_scores, start=1):
            medal = "🥇 " if rank == 1 else "🥈 " if rank == 2 else "🥉 " if rank == 3 else f"#{rank} "
            
            is_champ = player in champions_list
            champ_badge = "👑 **CHAMPION** " if is_champ else ""
            
            winnings = payout_results.get(player, 0)
            
            player_speeds = game_speeds.get(player, [])
            if player_speeds:
                avg_speed = sum(player_speeds) / len(player_speeds)
                multipliers = game_multipliers.get(player, [1.0])
                mults_str = ", ".join(f"{m:.2f}x" for m in multipliers)
                speed_str = f"Avg. Speed: `{avg_speed:.2f}s` | Round Multipliers: `{mults_str}`"
            else:
                speed_str = "No rounds won"
                
            podium_text += f"{medal}{champ_badge}**{player.display_name}** - `{score}` points\n" \
                           f"   ↳ *{speed_str}* | Won `{winnings}` {currency_name}\n"

        podium_emb.description = f"{podium_emb.description}{podium_text}"

        if scaling_factor < 1.0:
            podium_emb.add_field(
                name="⚖️ Economy Hard-Limit Applied",
                value=f"The total game payout reached `{total_payout_requested}` {currency_name}, which exceeded the guild cap of `{max_game_payout}`. Payouts were scaled down by `{scaling_factor:.2%}`.",
                inline=False
            )
            
        if len(champions_list) == 1:
            champion = champions_list[0]
            podium_emb.set_thumbnail(url=champion.display_avatar.url if hasattr(champion, "display_avatar") else champion.avatar_url)
            podium_emb.add_field(
                name="🏆 Overall Grand Winner!",
                value=f"{champion.mention} receives the End Game Reward of **`{payout_results[champion]}` {currency_name}**!",
                inline=False
            )
        else:
            champs_mention = ", ".join(c.mention for c in champions_list)
            podium_emb.add_field(
                name="🏆 Overall Grand Winners (Tie!)",
                value=f"It's a tie! {champs_mention} each receive a split of the End Game Reward: **`{base_end_reward // len(champions_list)}` {currency_name}**!",
                inline=False
            )

        podium_msg = await ctx.send(embed=podium_emb)
        self._schedule_final_cleanup(ctx.guild, podium_msg)

    @commands.command()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_messages=True)
    async def boozystop(self, ctx):
        """Forcefully stops any active quiz or game in the current channel."""
        channel = ctx.channel
        if channel.id not in self.active_quizzes:
            await ctx.send("❌ There is no active quiz or game running in this channel.")
            return

        task = self.running_tasks.get(channel.id)
        if task:
            task.cancel()
            self.running_tasks.pop(channel.id, None)

        self.active_quizzes.discard(channel.id)
        await ctx.send("🛑 The active quiz/game has been forcefully stopped, and all locks have been released.")

    @commands.group()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def boozyquizset(self, ctx):
        """Manage BoozyBank Quiz settings."""
        pass

    @boozyquizset.command()
    async def quizreward(self, ctx, amount: int):
        """Set the reward amount for answering a single quiz question correctly."""
        if amount < 0:
            await ctx.send("Reward cannot be negative.")
            return
        await self.config.guild(ctx.guild).quiz_reward.set(amount)
        await ctx.send(f"Quiz question reward set to `{amount}` coins.")

    @boozyquizset.command()
    async def timeout(self, ctx, seconds: int):
        """Set the answer timeout (between 10 and 120 seconds)."""
        if seconds < 10 or seconds > 120:
            await ctx.send("Choose a time limit between 10 and 120 seconds.")
            return
        await self.config.guild(ctx.guild).timeout.set(seconds)
        await ctx.send(f"Answer time limit set to `{seconds}` seconds.")

    @boozyquizset.command()
    async def model(self, ctx, model_name: str):
        """Set the OpenAI model (e.g. gpt-4o-mini, gpt-4o)."""
        await self.config.guild(ctx.guild).model.set(model_name)
        await ctx.send(f"OpenAI model set to `{model_name}`.")

    @boozyquizset.command()
    async def secondguess(self, ctx, toggle: bool):
        """Set whether players can make a second guess if they are wrong."""
        await self.config.guild(ctx.guild).allow_second_guess.set(toggle)
        status = "allowed" if toggle else "not allowed"
        await ctx.send(f"A second guess is now **{status}**.")

    @boozyquizset.command()
    async def showexplanation(self, ctx, toggle: bool):
        """Set whether to show the explanation after the quiz ends."""
        await self.config.guild(ctx.guild).show_explanation.set(toggle)
        status = "on" if toggle else "off"
        await ctx.send(f"Showing explanations is now **{status}**.")

    @boozyquizset.command()
    async def cleanup(self, ctx, toggle: bool):
        """Toggle whether to auto-delete question embeds and wrong answers after rounds."""
        await self.config.guild(ctx.guild).cleanup_messages.set(toggle)
        status = "enabled" if toggle else "disabled"
        await ctx.send(f"Message cleanup is now **{status}**.")

    @boozyquizset.command()
    async def finalcleanup(self, ctx, minutes: int):
        """Set the delay in minutes to delete final quiz embeds (0 to disable)."""
        if minutes < 0:
            await ctx.send("Delay cannot be negative.")
            return
        await self.config.guild(ctx.guild).final_cleanup_delay.set(minutes)
        if minutes == 0:
            await ctx.send("Final message cleanup has been **disabled**.")
        else:
            await ctx.send(f"Final message cleanup set to **{minutes}** minutes.")

    @boozyquizset.command()
    async def maxpayout(self, ctx, amount: int):
        """Set the maximum coin payout limit for a single multi-round game."""
        if amount < 100:
            await ctx.send("The game payout limit should be at least 100 coins.")
            return
        await self.config.guild(ctx.guild).max_game_payout.set(amount)
        await ctx.send(f"Maximum game payout limit set to `{amount}` coins.")

    @boozyquizset.group(name="endreward")
    async def _endreward(self, ctx):
        """Configure the end-game rewards based on game difficulty."""
        pass

    @_endreward.command(name="easy")
    async def easy_endreward(self, ctx, amount: int):
        """Set the end-game reward for winning an easy difficulty game."""
        if amount < 0:
            await ctx.send("Reward cannot be negative.")
            return
        await self.config.guild(ctx.guild).easy_endreward.set(amount)
        await ctx.send(f"Easy game winner reward set to `{amount}` coins.")

    @_endreward.command(name="medium")
    async def medium_endreward(self, ctx, amount: int):
        """Set the end-game reward for winning a medium difficulty game."""
        if amount < 0:
            await ctx.send("Reward cannot be negative.")
            return
        await self.config.guild(ctx.guild).medium_endreward.set(amount)
        await ctx.send(f"Medium game winner reward set to `{amount}` coins.")

    @_endreward.command(name="hard")
    async def hard_endreward(self, ctx, amount: int):
        """Set the end-game reward for winning a hard difficulty game."""
        if amount < 0:
            await ctx.send("Reward cannot be negative.")
            return
        await self.config.guild(ctx.guild).hard_endreward.set(amount)
        await ctx.send(f"Hard game winner reward set to `{amount}` coins.")

    @boozyquizset.group(name="topics")
    async def _topics(self, ctx):
        """Manage the list of default random topics."""
        pass

    @_topics.command(name="add")
    async def add_topic(self, ctx, *, topic: str):
        """Add a new topic to the default list."""
        topic = topic.strip()
        async with self.config.guild(ctx.guild).default_topics() as topics:
            if topic in topics:
                await ctx.send("This topic is already in the list.")
                return
            topics.append(topic)
        await ctx.send(f"Topic '{topic}' has been added to the list.")

    @_topics.command(name="remove")
    async def remove_topic(self, ctx, *, topic: str):
        """Remove a topic from the default list."""
        topic = topic.strip()
        async with self.config.guild(ctx.guild).default_topics() as topics:
            if topic not in topics:
                await ctx.send("This topic is not in the list.")
                return
            topics.remove(topic)
        await ctx.send(f"Topic '{topic}' has been removed from the list.")

    @_topics.command(name="list")
    async def list_topics(self, ctx):
        """Show all configured default topics."""
        topics = await self.config.guild(ctx.guild).default_topics()
        if not topics:
            await ctx.send("No default topics have been configured.")
            return
        formatted = "\n".join(f"- {t}" for t in topics)
        await ctx.send(f"**Default quiz topics:**\n{box(formatted)}")

    @boozyquizset.command()
    async def settings(self, ctx):
        """View the current BoozyBank Quiz settings."""
        config_guild = self.config.guild(ctx.guild)
        quiz = await config_guild.quiz_reward()
        timeout = await config_guild.timeout()
        model = await config_guild.model()
        second_guess = await config_guild.allow_second_guess()
        show_explanation = await config_guild.show_explanation()
        topics = await config_guild.default_topics()
        max_payout = await config_guild.max_game_payout()
        easy_end = await config_guild.easy_endreward()
        med_end = await config_guild.medium_endreward()
        hard_end = await config_guild.hard_endreward()
        cleanup = await config_guild.cleanup_messages()
        final_delay = await config_guild.final_cleanup_delay()

        currency_name = await bank.get_currency_name(ctx.guild)

        emb = discord.Embed(
            title="🍻 BoozyBank Quiz Settings 🍻",
            color=discord.Color.blue()
        )
        emb.add_field(name="🟢 Quiz Q Reward", value=f"`{quiz}` {currency_name}", inline=True)
        emb.add_field(name="⏱️ Time Limit", value=f"`{timeout}` seconds", inline=True)
        emb.add_field(name="🧠 OpenAI Model", value=f"`{model}`", inline=True)
        emb.add_field(name="🔄 Second Guess?", value="Allowed" if second_guess else "Not allowed", inline=True)
        emb.add_field(name="🧹 Message Cleanup?", value="Enabled" if cleanup else "Disabled", inline=True)
        emb.add_field(name="🧹 Final Cleanup Delay", value="Disabled" if final_delay == 0 else f"{final_delay} minutes", inline=True)
        emb.add_field(name="⚖️ Max Game Payout", value=f"`{max_payout}` {currency_name}", inline=True)
        emb.add_field(name="🥇 Easy EndReward", value=f"`{easy_end}` {currency_name}", inline=True)
        emb.add_field(name="🥇 Medium EndReward", value=f"`{med_end}` {currency_name}", inline=True)
        emb.add_field(name="🥇 Hard EndReward", value=f"`{hard_end}` {currency_name}", inline=True)
        emb.add_field(name="📝 Default Topics", value=f"`{len(topics)}` topics", inline=True)

        await ctx.send(embed=emb)

    @commands.command()
    @commands.guild_only()
    async def boozyquizstats(self, ctx, member: discord.Member = None):
        """View quiz statistics for yourself or another member."""
        if not member:
            member = ctx.author

        wins = await self.config.member(member).wins()
        earnings = await self.config.member(member).earnings()
        currency_name = await bank.get_currency_name(ctx.guild)

        emb = discord.Embed(
            title=f"📊 Trivia Stats for {member.display_name}",
            color=discord.Color.purple()
        )
        avatar_url = member.display_avatar.url if hasattr(member, "display_avatar") else member.avatar_url
        emb.set_thumbnail(url=avatar_url)
        emb.add_field(name="🏆 Total Wins", value=f"`{wins}` quiz rounds won", inline=False)
        emb.add_field(name="💰 Total Earned", value=f"`{earnings}` {currency_name}", inline=False)

        await ctx.send(embed=emb)

    @commands.command()
    @commands.guild_only()
    async def boozyquizleaderboard(self, ctx):
        """View the quiz leaderboard for this server."""
        all_members = await self.config.all_members(ctx.guild)
        if not all_members:
            await ctx.send("Nobody has won a quiz in this server yet!")
            return

        leaderboard_data = []
        for member_id, data in all_members.items():
            wins = data.get("wins", 0)
            earnings = data.get("earnings", 0)
            if wins > 0:
                leaderboard_data.append((member_id, wins, earnings))

        if not leaderboard_data:
            await ctx.send("Nobody has won a quiz in this server yet!")
            return

        leaderboard_data.sort(key=lambda x: x[1], reverse=True)

        currency_name = await bank.get_currency_name(ctx.guild)

        emb = discord.Embed(
            title="🏆 BoozyQuiz Top Players Leaderboard 🏆",
            color=discord.Color.gold(),
            description="The players with the most quiz round wins in this server!\n"
        )

        leaderboard_text = ""
        for index, (member_id, wins, earnings) in enumerate(leaderboard_data[:10], start=1):
            member = ctx.guild.get_member(member_id)
            name = member.display_name if member else f"Former Member ({member_id})"

            medal = ""
            if index == 1:
                medal = "🥇 "
            elif index == 2:
                medal = "🥈 "
            elif index == 3:
                medal = "🥉 "
            else:
                medal = f"#{index} "

            leaderboard_text += f"{medal}**{name}** - `{wins}` wins (`{earnings}` {currency_name})\n"

        emb.description = f"{emb.description}\n{leaderboard_text}"
        await ctx.send(embed=emb)
