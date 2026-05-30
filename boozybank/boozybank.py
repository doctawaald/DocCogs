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
            "easy_reward": 50,
            "medium_reward": 100,
            "hard_reward": 200,
            "timeout": 30,
            "show_explanation": True,
            "model": "gpt-4o-mini",
            "allow_second_guess": False,
            "max_game_payout": 1000,
            "grand_winner_bonus": 150,
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

    def _get_speed_multiplier(self, elapsed: float) -> tuple:
        """Returns the multiplier and a custom speed tier name based on response speed."""
        if elapsed <= 2.50:
            return 1.50, "⚡ Reflex Legend! (Under 2.50s)"
        elif elapsed <= 3.50:
            return 1.35, "🚀 Lightning Speed! (Under 3.50s)"
        elif elapsed <= 4.50:
            return 1.25, "🔥 Sonic Speed! (Under 4.50s)"
        elif elapsed <= 5.50:
            return 1.15, "🏃 Fast! (Under 5.50s)"
        elif elapsed <= 6.50:
            return 1.10, "⭐ Quick! (Under 6.50s)"
        else:
            return 1.00, "🐢 Standard (Over 6.50s)"

    async def _generate_quiz(self, guild: discord.Guild, topic: str, difficulty: str) -> dict:
        """Fetches a single quiz question from OpenAI via a non-blocking request."""
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
            if len(words) > 1 and words[-1].lower() in ["easy", "medium", "hard"]:
                difficulty = words[-1].lower()
                topic = " ".join(words[:-1]).strip()
            elif len(words) == 1 and words[0].lower() in ["easy", "medium", "hard"]:
                difficulty = words[0].lower()
            else:
                topic = topic_and_difficulty.strip()

        if not topic:
            default_topics = await self.config.guild(ctx.guild).default_topics()
            topic = random.choice(default_topics) if default_topics else "General Knowledge"

        self.active_quizzes.add(channel.id)

        emoji_beer = "🍻"
        generating_msg = await ctx.send(
            f"{emoji_beer} Generating an **{difficulty}** quiz question about **{topic}** via OpenAI... Please wait!"
        )

        try:
            quiz_data = await self._generate_quiz(ctx.guild, topic, difficulty)
        except Exception as e:
            self.active_quizzes.discard(channel.id)
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

        emb.set_footer(text=f"Type A, B, C, or D to answer! | Time limit: {timeout}s")

        await ctx.send(embed=emb)

        answered_users = set()
        start_time = time.time()
        winner = None
        elapsed = 0.0

        def check(m):
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

        while time.time() - start_time < timeout:
            remaining = timeout - (time.time() - start_time)
            if remaining <= 0:
                break
            try:
                msg = await self.bot.wait_for("message", check=check, timeout=remaining)
            except asyncio.TimeoutError:
                break

            ans_attempt = msg.content.strip().upper()
            answered_users.add(msg.author.id)

            if ans_attempt == correct_answer:
                winner = msg.author
                elapsed = time.time() - start_time
                try:
                    await msg.add_reaction("✅")
                except discord.HTTPException:
                    pass
                break
            else:
                try:
                    await msg.add_reaction("❌")
                except discord.HTTPException:
                    pass

        self.active_quizzes.discard(channel.id)

        if winner:
            base_reward_key = f"{difficulty}_reward"
            base_reward = await self.config.guild(ctx.guild).get_attr(base_reward_key)()
            
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
                description=f"Congratulations {winner.mention}! You were the fastest to answer correctly!\n\n"
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
            await ctx.send(embed=winner_emb)

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

            await ctx.send(embed=timeout_emb)

    @commands.command()
    @commands.guild_only()
    async def boozygame(self, ctx, rounds: int = 5, *, topic_and_difficulty: str = None):
        """Start a multi-round fast-paced trivia game!

        All questions are pre-generated in a single API call to keep the game incredibly fast-paced with zero delays.
        Features speed reflex multipliers and overall podium awards with anti-inflation caps.

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
            if len(words) > 1 and words[-1].lower() in ["easy", "medium", "hard"]:
                difficulty = words[-1].lower()
                topic = " ".join(words[:-1]).strip()
            elif len(words) == 1 and words[0].lower() in ["easy", "medium", "hard"]:
                difficulty = words[0].lower()
            else:
                topic = topic_and_difficulty.strip()

        if not topic:
            default_topics = await self.config.guild(ctx.guild).default_topics()
            topic = random.choice(default_topics) if default_topics else "General Knowledge"

        self.active_quizzes.add(channel.id)

        generating_msg = await ctx.send(
            f"🍻 Preparing a **{rounds}-round** fast-paced game about **{topic}** ({difficulty})...\n"
            f"Fetching all questions in advance for a lightning-fast experience! Please wait..."
        )

        try:
            questions = await self._generate_quiz_batch(ctx.guild, topic, difficulty, rounds)
        except Exception as e:
            self.active_quizzes.discard(channel.id)
            await generating_msg.delete()
            log.error(f"Error batch-generating quiz game: {e}", exc_info=True)
            await ctx.send(f"❌ Failed to load the trivia game: {e}")
            return

        await generating_msg.delete()

        game_scores = {}
        pending_payouts = {}
        currency_name = await bank.get_currency_name(ctx.guild)
        
        base_reward_key = f"{difficulty}_reward"
        base_reward = await self.config.guild(ctx.guild).get_attr(base_reward_key)()
        timeout = await self.config.guild(ctx.guild).timeout()
        allow_second_guess = await self.config.guild(ctx.guild).allow_second_guess()
        show_explanation = await self.config.guild(ctx.guild).show_explanation()

        await ctx.send(
            f"🎉 **BoozyGame Started!** 🎉\n"
            f"**Topic:** {topic} | **Difficulty:** {difficulty.capitalize()} | **Rounds:** {rounds}\n"
            f"Get ready, Round 1 is starting in 3 seconds..."
        )
        await asyncio.sleep(3.0)

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
            emb.set_footer(text=f"Type A, B, C, or D! | Round limit: {timeout}s")
            
            round_msg = await ctx.send(embed=emb)

            answered_users = set()
            start_time = time.time()
            winner = None
            elapsed = 0.0

            def check(m):
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

            while time.time() - start_time < timeout:
                remaining = timeout - (time.time() - start_time)
                if remaining <= 0:
                    break
                try:
                    msg = await self.bot.wait_for("message", check=check, timeout=remaining)
                except asyncio.TimeoutError:
                    break

                ans_attempt = msg.content.strip().upper()
                answered_users.add(msg.author.id)

                if ans_attempt == correct_answer:
                    winner = msg.author
                    elapsed = time.time() - start_time
                    try:
                        await msg.add_reaction("✅")
                    except discord.HTTPException:
                        pass
                    break
                else:
                    try:
                        await msg.add_reaction("❌")
                    except discord.HTTPException:
                        pass

            if winner:
                multiplier, speed_tier = self._get_speed_multiplier(elapsed)
                payout = int(base_reward * multiplier)
                
                game_scores[winner] = game_scores.get(winner, 0) + 1
                pending_payouts[winner] = pending_payouts.get(winner, 0) + payout

                round_win_emb = discord.Embed(
                    title=f"🎯 Round {index} Won!",
                    color=discord.Color.green(),
                    description=f"{winner.mention} got it right! Answer was **{correct_answer}** ({options[correct_answer]})\n\n"
                                f"⏱️ **Speed:** `{elapsed:.2f}` seconds\n"
                                f"⚡ **Speed Rank:** {speed_tier}\n"
                                f"💰 **Pending Reward:** `{payout}` {currency_name} *(Multiplier: {multiplier}x)*"
                )
                if show_explanation and explanation:
                    round_win_emb.add_field(name="ℹ️ Explanation", value=explanation, inline=False)
                
                await ctx.send(embed=round_win_emb)
            else:
                round_timeout_emb = discord.Embed(
                    title=f"⏰ Round {index} - Time is up!",
                    color=discord.Color.red(),
                    description=f"Nobody guessed correctly in time!\n\n"
                                f"**Correct Answer:** **{correct_answer}** ({options[correct_answer]})"
                )
                if show_explanation and explanation:
                    round_timeout_emb.add_field(name="ℹ️ Explanation", value=explanation, inline=False)
                
                await ctx.send(embed=round_timeout_emb)

            if index < rounds:
                await ctx.send(f"Round {index+1} is starting in 5 seconds...")
                await asyncio.sleep(5.0)

        self.active_quizzes.discard(channel.id)

        if not game_scores:
            await ctx.send("🏁 **Game Over!** Nobody won any rounds, so no coins will be distributed.")
            return

        sorted_scores = sorted(game_scores.items(), key=lambda x: x[1], reverse=True)
        max_score = sorted_scores[0][1]
        
        grand_winners = [member for member, score in sorted_scores if score == max_score]
        grand_bonus = await self.config.guild(ctx.guild).grand_winner_bonus()

        for winner in grand_winners:
            pending_payouts[winner] = pending_payouts.get(winner, 0) + grand_bonus

        max_game_payout = await self.config.guild(ctx.guild).max_game_payout()
        total_payout_requested = sum(pending_payouts.values())

        scaling_factor = 1.0
        if total_payout_requested > max_game_payout:
            scaling_factor = max_game_payout / total_payout_requested

        payout_results = {}
        for player, amount in pending_payouts.items():
            final_payout = int(amount * scaling_factor)
            payout_results[player] = final_payout

            try:
                await bank.deposit_credits(player, final_payout)
            except bank.errors.BalanceTooHigh:
                pass

            wins_to_add = game_scores.get(player, 0)
            current_wins = await self.config.member(player).wins()
            current_earnings = await self.config.member(player).earnings()
            
            await self.config.member(player).wins.set(current_wins + wins_to_add)
            await self.config.member(player).earnings.set(current_earnings + final_payout)

        podium_emb = discord.Embed(
            title="🏁 Trivia Game Over! Final Scores 🏁",
            color=discord.Color.gold(),
            description=f"**Topic:** {topic} | **Difficulty:** {difficulty.capitalize()}\n"
                        f"Thank you for playing BoozyGame! Here are the champions:\n\n"
        )

        podium_text = ""
        for rank, (player, score) in enumerate(sorted_scores, start=1):
            medal = "🥇 " if rank == 1 else "🥈 " if rank == 2 else "🥉 " if rank == 3 else f"#{rank} "
            final_coins = payout_results.get(player, 0)
            
            champ_badge = "👑 **GRAND CHAMPION** " if player in grand_winners else ""
            podium_text += f"{medal}{champ_badge}**{player.display_name}** - `{score}` Correct Answers | Won `{final_coins}` {currency_name}\n"

        podium_emb.description = f"{podium_emb.description}{podium_text}"

        if scaling_factor < 1.0:
            podium_emb.add_field(
                name="⚖️ Economy Hard-Limit Applied",
                value=f"Total rewards reached `{total_payout_requested}` {currency_name}, exceeding the cap of `{max_game_payout}`. Payouts were automatically scaled by `{scaling_factor:.2%}` to protect the economy.",
                inline=False
            )
            
        if len(grand_winners) == 1:
            champion = grand_winners[0]
            podium_emb.set_thumbnail(url=champion.display_avatar.url if hasattr(champion, "display_avatar") else champion.avatar_url)
            podium_emb.add_field(
                name="🍻 Cheers to the Winner!",
                value=f"{champion.mention} receives an extra `{grand_bonus}` {currency_name} Grand Winner Bonus for topping the board!",
                inline=False
            )
        else:
            champs_mention = ", ".join(c.mention for c in grand_winners)
            podium_emb.add_field(
                name="🍻 Cheers to the Winners!",
                value=f"It's a tie! {champs_mention} each receive a `{grand_bonus}` {currency_name} Grand Winner Bonus!",
                inline=False
            )

        await ctx.send(embed=podium_emb)

    @commands.group()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def boozyquizset(self, ctx):
        """Manage BoozyBank Quiz settings."""
        pass

    @boozyquizset.command()
    async def easy(self, ctx, amount: int):
        """Set the reward amount for easy quiz questions."""
        if amount < 0:
            await ctx.send("Reward cannot be negative.")
            return
        await self.config.guild(ctx.guild).easy_reward.set(amount)
        await ctx.send(f"Easy reward set to `{amount}` coins.")

    @boozyquizset.command()
    async def medium(self, ctx, amount: int):
        """Set the reward amount for medium quiz questions."""
        if amount < 0:
            await ctx.send("Reward cannot be negative.")
            return
        await self.config.guild(ctx.guild).medium_reward.set(amount)
        await ctx.send(f"Medium reward set to `{amount}` coins.")

    @boozyquizset.command()
    async def hard(self, ctx, amount: int):
        """Set the reward amount for hard quiz questions."""
        if amount < 0:
            await ctx.send("Reward cannot be negative.")
            return
        await self.config.guild(ctx.guild).hard_reward.set(amount)
        await ctx.send(f"Hard reward set to `{amount}` coins.")

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
    async def maxpayout(self, ctx, amount: int):
        """Set the maximum coin payout limit for a single multi-round game."""
        if amount < 100:
            await ctx.send("The game payout limit should be at least 100 coins.")
            return
        await self.config.guild(ctx.guild).max_game_payout.set(amount)
        await ctx.send(f"Maximum game payout limit set to `{amount}` coins.")

    @boozyquizset.command()
    async def grandbonus(self, ctx, amount: int):
        """Set the coin bonus awarded to the overall game winner."""
        if amount < 0:
            await ctx.send("Bonus cannot be negative.")
            return
        await self.config.guild(ctx.guild).grand_winner_bonus.set(amount)
        await ctx.send(f"Grand winner bonus set to `{amount}` coins.")

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
        easy = await config_guild.easy_reward()
        medium = await config_guild.medium_reward()
        hard = await config_guild.hard_reward()
        timeout = await config_guild.timeout()
        model = await config_guild.model()
        second_guess = await config_guild.allow_second_guess()
        show_explanation = await config_guild.show_explanation()
        topics = await config_guild.default_topics()
        max_payout = await config_guild.max_game_payout()
        grand_bonus = await config_guild.grand_winner_bonus()

        currency_name = await bank.get_currency_name(ctx.guild)

        emb = discord.Embed(
            title="🍻 BoozyBank Quiz Settings 🍻",
            color=discord.Color.blue()
        )
        emb.add_field(name="🟢 Easy Reward", value=f"`{easy}` {currency_name}", inline=True)
        emb.add_field(name="🟡 Medium Reward", value=f"`{medium}` {currency_name}", inline=True)
        emb.add_field(name="🔴 Hard Reward", value=f"`{hard}` {currency_name}", inline=True)
        emb.add_field(name="⏱️ Time Limit", value=f"`{timeout}` seconds", inline=True)
        emb.add_field(name="🧠 OpenAI Model", value=f"`{model}`", inline=True)
        emb.add_field(name="🔄 Second Guess?", value="Allowed" if second_guess else "Not allowed", inline=True)
        emb.add_field(name="ℹ️ Show Explanation?", value="Yes" if show_explanation else "No", inline=True)
        emb.add_field(name="⚖️ Max Game Payout", value=f"`{max_payout}` {currency_name}", inline=True)
        emb.add_field(name="👑 Grand Winner Bonus", value=f"`{grand_bonus}` {currency_name}", inline=True)
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
