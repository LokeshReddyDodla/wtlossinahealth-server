# Gamification — Flutter Integration Guide

Base URL: `/v1/gamification`
Auth: All endpoints require patient or care provider JWT token.

---

## 1. Player Profile (Home Screen Widget)

**Show on**: Home screen, always visible

```
GET /v1/gamification/patients/{patient_id}/profile
```

Response:
```json
{
  "level": 12,
  "title": "Committed",
  "total_xp": 5430,
  "current_streak": 14,
  "longest_streak": 21,
  "streak_freezes": 2,
  "streak_multiplier": 1.2,
  "xp_to_next_level": 870,
  "leaderboard_visibility": "group_only"
}
```

**UI Elements**:
- Level badge + title ("Level 12 — Committed")
- XP progress bar (current XP / next level threshold)
- Streak counter with fire icon (🔥 14 days)
- Streak freeze count (❄️ ×2)

**Update visibility**:
```
PATCH /v1/gamification/patients/{patient_id}/profile
Body: { "leaderboard_visibility": "public" }
```

---

## 2. Daily Tasks (Main Gamification Screen)

**Show on**: Dedicated "Today" tab or daily goals section

```
GET /v1/gamification/patients/{patient_id}/daily?date=2026-04-03
```

Response:
```json
{
  "date": "2026-04-03",
  "tasks": [
    {
      "task_id": "uuid",
      "task_type": "LOG_MEAL",
      "title": "Log your meals",
      "description": "Track what you eat today",
      "source_type": "habit",
      "target_value": null,
      "current_value": null,
      "status": "pending",
      "xp_reward": 15,
      "completed_at": null
    },
    {
      "task_type": "HIT_STEP_GOAL",
      "title": "Walk 8000 steps",
      "target_value": 8000,
      "current_value": 3200,
      "status": "pending",
      "xp_reward": 30
    }
  ],
  "completed_count": 2,
  "total_count": 6,
  "xp_earned_today": 45,
  "streak_status": "active"
}
```

**UI Elements**:
- Task list with checkboxes (green = completed, grey = pending)
- Progress ring: "4/6 tasks done"
- XP earned today counter
- Each task shows: icon, title, XP reward, target/current for measurable tasks

**Manual task completion** (logging tasks only):
```
POST /v1/gamification/patients/{patient_id}/tasks/{task_id}/complete
```
Returns: `{ "xp_earned": 15, "new_total_xp": 5445, "level_up": false, "achievements_unlocked": [] }`

> **Important**: Only `LOG_MEAL`, `LOG_SLEEP`, `LOG_MOOD`, `LOG_GLUCOSE`, `LOG_WEIGHT` can be manually completed. Target-based tasks (`HIT_STEP_GOAL`, `HIT_CALORIE_TARGET`, etc.) auto-complete when the actual data is synced. Show them as read-only progress bars, not tappable checkboxes.

**Auto-completion flow**: When user logs a meal via the existing meal screen, the backend hook auto-completes the `LOG_MEAL` task. Poll `GET /daily` to refresh, or use push notifications.

---

## 3. Weekly Quest

**Show on**: Daily tasks screen, highlighted section

```
GET /v1/gamification/patients/{patient_id}/quests/current
```

Response:
```json
{
  "quest_id": "uuid",
  "title": "Meal Tracker",
  "description": "Log meals on 5 of 7 days this week",
  "target_value": 5,
  "current_value": 3,
  "progress_pct": 0.6,
  "xp_reward": 100,
  "status": "active"
}
```

**UI**: Progress bar with "3/5 days — 100 XP reward"

---

## 4. Achievements

**Show on**: Dedicated achievements screen (tab or profile sub-page)

```
GET /v1/gamification/patients/{patient_id}/achievements
```

Response: List of all achievements with progress:
```json
[
  {
    "slug": "streak_7",
    "title": "Week Warrior",
    "description": "Maintain a 7-day streak",
    "icon": "streak_bronze",
    "category": "consistency",
    "tier": "bronze",
    "xp_reward": 50,
    "earned": true,
    "earned_at": "2026-03-28T10:30:00",
    "progress_pct": 1.0,
    "starred_by": null
  },
  {
    "slug": "streak_14",
    "title": "Two Week Strong",
    "earned": false,
    "progress_pct": 0.71,
    ...
  }
]
```

**Recent achievements** (for notification badges):
```
GET /v1/gamification/patients/{patient_id}/achievements/recent
```

**UI Elements**:
- Grid of badges organized by category (Consistency, Nutrition, Fitness, Wellness, Social, Milestones)
- Earned: full color with checkmark. Unearned: greyed out with progress bar
- Tier colors: Bronze, Silver, Gold, Platinum
- Hidden achievements: don't show until earned
- Starred achievements: show star icon from care provider
- On earn: show celebration animation + push notification

---

## 5. Streak Freeze

**Manual freeze** (for planned absences like vacations):
```
POST /v1/gamification/patients/{patient_id}/streak/freeze
```

**UI**: Button in streak section: "Use freeze (2 remaining)" — confirm dialog explaining the streak will pause for one day

---

## 6. XP History

```
GET /v1/gamification/patients/{patient_id}/history?period=week
```

Response:
```json
{
  "period": "week",
  "entries": [
    { "date": "2026-04-01", "xp_earned": 175, "tasks_completed": 5 },
    { "date": "2026-04-02", "xp_earned": 190, "tasks_completed": 6 }
  ],
  "total_xp_period": 1050
}
```

**UI**: Bar chart showing daily XP over the week/month

---

## 7. Buddies

### List buddies
```
GET /v1/gamification/patients/{patient_id}/buddies
```

### Send buddy request
```
POST /v1/gamification/patients/{patient_id}/buddies/request
Body: { "accepter_id": "uuid-of-other-patient" }
```
> Limited to same facility. Max 5 requests/day. Max 3 active buddies.

### Accept request
```
POST /v1/gamification/patients/{patient_id}/buddies/{buddy_id}/accept
```

### Remove buddy
```
DELETE /v1/gamification/patients/{patient_id}/buddies/{buddy_id}
```

### Buddy progress
```
GET /v1/gamification/patients/{patient_id}/buddies/{buddy_id}/progress
```

Response:
```json
{
  "buddy_name": "Mina",
  "level": 15,
  "title": "Achiever",
  "current_streak": 21,
  "tasks_completed_today": 4,
  "tasks_total_today": 6,
  "recent_achievements": ["streak_14", "meal_streak_7"]
}
```

**UI Elements**:
- Buddy cards showing name, level, streak
- "Add Buddy" button → search by name within facility
- Buddy detail: their daily progress (no health data — only tasks/streak/achievements)
- Buddy streak counter between the two of you

**Privacy**: Buddies can ONLY see: level, streak, task completion %, achievements. NO health data (no glucose, weight, meals, symptoms).

---

## 8. Groups

### My groups
```
GET /v1/gamification/patients/{patient_id}/groups
```

### Create group (patients can create "patient_created" type only)
```
POST /v1/gamification/groups
Body: { "name": "Morning Walkers", "group_type": "patient_created", "max_members": 20 }
```

### Join / Leave
```
POST /v1/gamification/groups/{group_id}/join
DELETE /v1/gamification/groups/{group_id}/leave
```

### Group members
```
GET /v1/gamification/groups/{group_id}/members
```

### Group leaderboard
```
GET /v1/gamification/groups/{group_id}/leaderboard?board_type=weekly_xp
```

### Group feed
```
GET /v1/gamification/groups/{group_id}/feed
```

**UI Elements**:
- Group list with member count, your rank
- Group detail: member list (name, level, streak), leaderboard, activity feed
- "Create Group" button for patients
- Care provider groups show as "Dr. Ahmed's Weight Loss Group"

---

## 9. Challenges

### Available challenges (opt-in)
```
GET /v1/gamification/challenges/available
```

### My active challenges
```
GET /v1/gamification/patients/{patient_id}/challenges/active
```

### Join / Withdraw
```
POST /v1/gamification/challenges/{challenge_id}/join
POST /v1/gamification/challenges/{challenge_id}/withdraw
```

### Challenge detail + leaderboard
```
GET /v1/gamification/challenges/{challenge_id}
```

Response:
```json
{
  "challenge": {
    "title": "April Steps Challenge",
    "challenge_type": "monthly",
    "scope": "group_competitive",
    "metric_type": "steps",
    "target_value": 200000,
    "duration_days": 30,
    "xp_reward": 150,
    "bonus_xp_winner": 50,
    "participant_count": 12
  },
  "my_progress": {
    "current_value": 62000,
    "status": "active",
    "rank": 3
  },
  "leaderboard": [
    { "rank": 1, "patient_name": "Ravi", "current_value": 85000, "level": 20 },
    { "rank": 2, "patient_name": "Anonymous", "current_value": 74000, "level": 15 }
  ]
}
```

**UI**: Challenge card with progress bar, rank, leaderboard. Anonymous names for patients with `group_only` visibility outside their group.

---

## 10. Leaderboards

```
GET /v1/gamification/leaderboards/{board_type}?scope=global&scope_id=
```

Board types: `weekly_xp`, `monthly_xp`, `weekly_steps`, `streak`
Scopes: `global`, `facility`, `group`, `challenge`

**UI**: Tab bar for board types, scope selector (My Group / My Facility / Global)

---

## 11. Activity Feed + Cheers

### Buddy feed
```
GET /v1/gamification/patients/{patient_id}/feed/buddies
```

### Group feed
```
GET /v1/gamification/groups/{group_id}/feed
```

Feed events:
```json
{
  "actor_name": "Mina",
  "event_type": "achievement_earned",
  "event_data": { "title": "Week Warrior", "tier": "bronze" },
  "cheer_count": 3,
  "my_cheer": null
}
```

### Send cheer
```
POST /v1/gamification/feed/{feed_event_id}/cheer
Body: { "reaction": "fire" }
```

Reactions: `applause` 👏, `strong` 💪, `fire` 🔥, `star` ⭐
Max 3 cheers/day (grants 5 XP each to sender).

**UI**: Feed cards with event description, cheer button row, cheer count

---

## 12. Care Provider Screens

### Engagement dashboard
```
GET /v1/gamification/care-providers/{cp_id}/overview
```

Shows: all patients with level, streak, weekly tasks, at-risk flag

### At-risk patients
```
GET /v1/gamification/care-providers/{cp_id}/at-risk
```

Patients inactive >3 days

### Create challenge
```
POST /v1/gamification/care-providers/{cp_id}/challenges
Body: {
  "title": "April Steps Challenge",
  "challenge_type": "monthly",
  "scope": "group_competitive",
  "metric_type": "steps",
  "target_value": 200000,
  "duration_days": 30,
  "xp_reward": 150,
  "patient_ids": ["uuid1", "uuid2"],
  "group_ids": ["group-uuid"]
}
```

### Star achievement
```
POST /v1/gamification/care-providers/{cp_id}/achievements/{achievement_id}/star
```

### My groups
```
GET /v1/gamification/care-providers/{cp_id}/groups
```

---

## 13. Push Notifications

The backend sends FCM notifications for:
- Achievement earned → "Achievement unlocked: Week Warrior"
- Level up → "You reached level 12!"
- Streak milestone (7/14/30/60/90) → "You're on a 14-day streak!"
- Challenge completed/won → "You completed April Steps Challenge!"
- Buddy cheered you → "A buddy reacted to your progress"

Flutter should handle these notification types and deep-link to the relevant screen.

---

## 14. Suggested Screen Structure

```
Home
├── Profile widget (level, XP bar, streak)
├── Today's Tasks (daily goals)
│   └── Weekly Quest card
└── Quick stats (XP earned today)

Gamification Tab
├── Achievements grid
├── XP History chart
├── Leaderboards (tabs: Weekly XP, Steps, Streak)
└── Challenges (active + available)

Social Tab
├── Buddies list + progress
├── Groups list
│   ├── Group detail (members, leaderboard, feed)
│   └── Group challenges
└── Activity Feed (buddy + group)

Care Provider Dashboard
├── Patient engagement table
├── At-risk patients alert
├── Challenge management
└── Group management
```

---

## 15. Polling / Refresh Strategy

| Screen | Refresh | Why |
|--------|---------|-----|
| Daily tasks | On screen open + after any health action (meal log, etc.) | Tasks auto-complete via backend hooks |
| Profile | On app open + after task completion response | XP/level may change |
| Achievements | On screen open + on push notification | New achievements |
| Leaderboards | On screen open (refreshed every 15 min server-side) | Not real-time |
| Feed | On screen open + pull-to-refresh | Social content |
| Buddy progress | On screen open | Other person's data |

The `complete_task` response includes `xp_earned`, `new_total_xp`, `level_up`, and `achievements_unlocked` — use these to update the UI immediately without re-fetching the profile.
