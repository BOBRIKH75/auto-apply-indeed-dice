# Auto-Apply Indeed + Dice

AI Agent that automatically applies to Java/Spring Boot contract jobs on Indeed and Dice every day.

## What it does

1. **Logs into Indeed/Dice** with your credentials
2. **Searches** for Java Spring Boot contract remote jobs
3. **Applies** via Easy Apply (fills forms, answers screening questions)
4. **Tracks** what you already applied to (no duplicates)
5. **Emails you** a report: "Applied to X jobs today"
6. **Runs daily** at 11:00 AM MT via GitHub Actions

## Anti-Detection Features

- Uses **Firefox** (less detected than Chrome)
- **Human-like delays** (15-45 sec between applications)
- **Random mouse movements** and scrolling
- **Stealth scripts** to hide automation markers
- **Session time limits** (max 25 min to avoid timeouts)
- **Rate limiting** (max 20 applications per platform per day)

## Setup

### 1. Create GitHub repo

```bash
gh repo create BOBRIKH75/auto-apply-indeed-dice --private --source=. --push
```

### 2. Add secrets (Settings → Secrets → Actions)

| Secret | Value |
|--------|-------|
| `INDEED_EMAIL` | Your Indeed login email |
| `INDEED_PASSWORD` | Your Indeed password |
| `DICE_EMAIL` | Your Dice login email |
| `DICE_PASSWORD` | Your Dice password |
| `RESEND_KEY` | Resend API key for email reports |

### 3. Make sure your Indeed/Dice profiles are COMPLETE

- Resume uploaded
- Phone number set
- Location: Parker, CO (or Remote)
- Work authorization: "Authorized to work for any employer"

### 4. Run manually to test

```bash
gh workflow run "Auto-Apply Indeed + Dice — Daily" -R BOBRIKH75/auto-apply-indeed-dice
```

## Daily Schedule

- **11:00 AM MT**: Indeed (20 applications) + Dice (20 applications)
- **Total**: Up to 40 real applications per day
- **Email report**: Sent after each run

## Important Notes

- Keep your Indeed/Dice profiles up to date (resume, phone, location)
- Don't also manually mass-apply at the same time (combined rate = suspicious)
- If you get a CAPTCHA challenge, the bot will skip that job and move on
- Max 20 per platform per day = safe rate that doesn't trigger bans
