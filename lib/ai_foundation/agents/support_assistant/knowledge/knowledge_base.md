# AI-Health patient app — support knowledge base

This is the only source of truth for the assistant. If something is not here, the
assistant does not know it. Navigation names in **bold** are real screen or button
names. Anything described without bold is a feature-level description; the assistant
should say "look for" rather than assert an exact label for those.

## 1. What the app is

AI-Health is a patient app used together with a clinic or care team. Patients log meals
(photo, text or voice), track glucose (CGM sensor, finger-prick readings, or both), sync
steps, sleep and vitals from their phone, upload lab reports and other documents, follow
diet and fitness plans written by their care team, receive prescriptions and medication
reminders, chat with their care team, and talk to an AI health companion about their own
data. The clinic sees the same data on a provider dashboard.

Removed feature: the weight-loss / GLP-1 coaching program no longer exists in the app.
If asked, say it is no longer part of AI-Health and that the care team can advise on
alternatives.

## 2. Login and account

- Sign-in is by **phone number + OTP**. The OTP is sent by the phone-verification
  provider (Firebase), not by AI-Health's own servers, so support cannot resend it
  manually.
- OTP troubleshooting: check the number and country code, wait 60 seconds before
  requesting again, make sure the phone has signal and is not in airplane mode, check
  SMS blocking or spam filters, try restarting the phone. If OTPs still never arrive
  after several tries, a human must look into it (hold).
- The account is created automatically the first time a phone number signs in. Signing
  in with a different number creates a different, empty account. If the patient sees an
  empty account, the most likely cause is a different number or country code than the
  one they used before.
- Email is optional profile information, not a login method.
- **Sign Out** is at the bottom of the Settings screen. Signing out and back in is a
  safe first fix for stale data or a screen that refuses to load.
- Deleting the account or all data is a human action (hold).

## 3. Settings screen map

Settings has these sections and entries (real names):

- **Account** → **Edit Profile**
- **General** → **Manage Permissions** ("Control app permissions"),
  **Connected Apps** ("Control connected apps"), **Notifications**,
  **Care Services** ("Manage your care package and providers")
- **Legal & Compliance** → **Privacy Policy**, **Safety & Sources**
- **Sign Out**

## 4. Profile and onboarding

- The app asks for a basic profile (name, gender, date of birth, height, weight),
  lifestyle (activity, eating, alcohol, smoking, sleep habits) and medical history
  (diabetes history). The app keeps reminding the patient to "complete your profile"
  until every required field in those three groups is filled. Clearing a required field
  later brings the reminder back.
- Profile edits are under **Edit Profile**. Changes save as you go.
- **Timezone** matters: meal dates, day screens, reminders and reports all use the
  timezone on the profile. If reminders arrive at odd hours or a meal shows on the
  wrong day, check the timezone first.
- **Language**: the AI companion and the assistant reply in the patient's preferred AI
  language, which is set in the app's settings/profile area. The human care team may
  reply in their own language.

## 5. App permissions

**Manage Permissions** lists five permissions, each with a switch:

| Permission | Why the app asks | What breaks without it |
|---|---|---|
| **Notifications** | Reminders, alerts, chat and support replies | No push notifications at all |
| **Health** | Reads steps, sleep, heart rate and similar data from the phone's health platform (Health Connect on Android, Apple Health on iOS) | Steps, sleep and vitals do not sync |
| **Camera** | Photographing meals, prescriptions and documents | "Take one" photo option fails |
| **Gallery** | Choosing existing photos for meals and reports | "Choose from gallery" fails |
| **Storage** | Saving captured images on the device | Photo capture may fail to save |

How to fix a permission that shows as denied:

1. Open **Settings → Manage Permissions** and turn the switch on. The app will ask the
   phone for the permission.
2. If the phone does not ask, or the switch turns itself back off, the permission was
   blocked at phone level. Android: phone Settings → Apps → AI-Health → Permissions →
   allow the item. iOS: phone Settings → AI-Health → allow the item. For Health on iOS:
   phone Settings → Health → Data Access & Devices → AI-Health. For Health Connect on
   Android: open the Health Connect app → App permissions → AI-Health → allow.
3. Return to the app and open **Manage Permissions** again so the app re-checks and
   syncs the new state.

The app reports the permission state to the server, so the assistant can see whether a
permission is currently on or off (see snapshot). If the snapshot says a permission is
off, say so and give the steps above.

## 6. Meals

Logging a meal is a two-step flow: the app shows a **preview** of what it recognised,
the patient confirms, then the meal is saved. Nothing is saved until the patient
confirms.

- Open **Meal Upload**. Choose **Meal Type** (Breakfast, Lunch, Dinner, Snack) and
  **Meal Time**. Add a photo with **Take one** (camera) or **Choose from gallery**, or
  type a **Meal Description**, or use voice logging where available. Confirm the preview
  to save.
- **Update Meal** re-runs the preview and replaces the meal. Meals can also be deleted.
- Saved meals appear in the meal overview and on the day screen for the date chosen.

Common problems and fixes:

- "Unable to upload meal" / photo option does nothing → Camera, Gallery or Storage
  permission is off (section 5), or the phone has no internet. Fix permission, check
  connection, retry.
- Preview takes long or fails → poor network or a very large photo. Move to better
  signal, retake a smaller or clearer photo, or describe the meal in text instead.
- Food recognised wrongly → edit the items in the preview before confirming, or use
  **Update Meal** afterwards.
- Meal missing from today → check the **Meal Time** date that was chosen and the
  profile timezone; the meal may be under a different day.
- Meal saved twice → delete the duplicate from the meal list.
- The app never shows "saved" → the preview was not confirmed; nothing was stored.
  Log the meal again and confirm.

The assistant can see the date of the last saved meal and how many meals were saved in
the last 7 days (snapshot). Use it to confirm whether recent meals actually reached the
server.

## 7. Glucose: CGM sensor, LibreView, Sinocare and manual readings

### 7a. How CGM data reaches the app

For FreeStyle Libre sensors the data path is: sensor → the patient's **LibreLink** app on
their phone → Abbott's **LibreView** cloud → AI-Health. AI-Health does not talk to the
sensor directly. Every link in that chain must be working.

Requirements on the patient's side:

1. The **LibreLink** app is installed, signed in, and the sensor is started in it.
2. The phone has Bluetooth on (for Libre 2/3 streaming) and internet, and the LibreLink
   app is allowed to run in the background.
3. The patient's LibreView account is connected to the clinic's LibreView practice, and
   the same **Libreview ID** is entered in AI-Health under **Settings → Connected Apps →
   Libreview → Libreview ID**.
4. Optional, for near-real-time readings: in LibreLink the patient shares readings with
   the clinic's LibreLinkUp connection (LibreLink → Connected Apps → LibreLinkUp → add
   the clinic's connection). The care team provides the clinic's connection details.

### 7b. When data updates

- Automatic full syncs from LibreView run about three times a day: around 7 am, 10 am
  and 5 pm India time. Readings from the sensor appear after the next sync.
- If the LibreLinkUp share is active, readings are polled about every 5 minutes.
- **Sync Now** under **Connected Apps → Libreview** forces a sync. It can be used once
  every 2 hours; the screen shows "Sync available in …" during the cooldown.
- Sync can be **paused** and **resumed** from the same screen. A paused connection
  never updates.

The assistant can see, per glucose source: sync status (active or paused), the last
successful sync time, the last reading time, and whether live polling is enabled
(snapshot). Use these to say precisely what is happening, for example "your last
successful sync was on <date>; readings after that have not arrived yet".

### 7c. Sensor problems (what to check, in order)

1. **New sensor, no readings yet**: new sensors have a warm-up period (typically about an
   hour) before the first reading. Then readings need one sync to reach AI-Health.
2. **Sensor expired**: Libre sensors last 14 days. LibreLink shows the days remaining.
   An expired sensor must be replaced; AI-Health cannot extend it.
3. **"Signal loss" / no readings in LibreLink itself**: keep the phone within range,
   Bluetooth on, LibreLink open once, phone not in battery-saver mode that kills
   background apps. If LibreLink has no readings, AI-Health cannot have them either.
4. **Readings in LibreLink but not in AI-Health**: check **Connected Apps → Libreview**:
   the Libreview ID is correct, sync is not paused, then tap **Sync Now** (or wait for
   the next scheduled sync). If the last sync time is old and Sync Now fails, hold.
5. **Sensor fell off, sensor error, replacement needed**: this is hardware. The patient
   should contact their care team or facility, or Abbott's customer care for the sensor
   itself. The assistant cannot arrange a replacement (hold, so the care team is aware).
6. **Readings look wrong compared to a finger-prick**: small differences are normal for
   CGM. Large, persistent differences should be raised with the care team (medical
   question → redirect).

### 7d. Sinocare and other CGM sources

Sinocare devices are connected by the care provider, not by the patient, and sync is
managed by the clinic. If Sinocare data stops, the care team must check it (hold).
Care providers can also upload LibreView, Linx or Sinocare export files on the patient's
behalf.

### 7e. Manual glucose readings

Finger-prick readings are entered under **SMBG Upload**: enter the **Glucose Reading**,
choose **Before Meal**, **After Meal** or **Random**, set the time, and save. "Failed to
upload smbg" usually means no internet; retry when connected. Manual readings show as
dots on the day screen.

## 8. Steps, sleep, heart rate and vitals

- Steps, sleep and heart rate come from the phone's health platform (Health Connect on
  Android, Apple Health on iOS) and are sent by the app when it is opened. They need the
  **Health** permission (section 5). Data from a watch or band must first reach the
  phone's health platform through the watch's own app.
- If steps or sleep are missing: confirm the Health permission is on, open the app so it
  can sync, confirm the watch app has synced to Health Connect / Apple Health, and check
  that today's data exists there. Sync is not instant; give it a few minutes after
  opening the app.
- Blood pressure and other vitals can be entered manually under **Vitals Upload**.

## 9. Documents, lab reports and InBody scans

- **Reports / documents**: upload lab reports and other documents as PDF, Word files or
  clear photos. Each file is processed immediately: the text is read (photos go through
  text recognition), summarised and stored. Files with no readable text (blurry or dark
  photos, screenshots at low resolution) are rejected for that file only; the other files
  in the same upload still succeed. If a document is missing from the list, that file's
  upload failed. Retake a clear, well-lit, straight photo or upload the PDF instead.
- The assistant can see the most recent documents that reached the server (snapshot).
- **InBody scan sheets** are uploaded through **Scanner**. A scan goes through the
  states uploaded → extracting → extracted. "Needs review" means the sheet was read with
  low confidence and the care team will check it. "Failed" means the sheet could not be
  read; re-upload a clearer image or the original PDF.
- **Daily Report** and **Weekly Report** under **Reports** summarise glucose, meals,
  sleep and activity. They need data for that period; an empty report means no data was
  received for it.

## 10. Care team, care services and emergencies

- **Care Services** shows the patient's care package and assigned care providers.
  **Add CareProvider** links a provider using the code the clinic gives the patient.
  Packages are also joined by a code from the clinic.
- Chatting with the care team happens in the app's chat. Chats are created when a
  provider is assigned; if a chat is missing, the assignment is missing (hold).
- The assistant can see the assigned care providers' names, roles, phone numbers and
  emails, and the facility's phone, emergency phone and operating hours (snapshot).
  When a patient asks how to reach their doctor or care team, give these directly.
- If no care provider is assigned, say so and hold so the facility can assign one.
- **Emergency**: for chest pain, breathing difficulty, fainting, seizure, stroke signs,
  severe low glucose with confusion or unconsciousness, or any situation that feels
  life-threatening, the patient must call emergency services immediately: **108**
  (ambulance) or **112** (all emergencies) in India, or the local emergency number
  elsewhere. Then contact the facility's emergency phone if one is listed. The assistant
  never gives medical instructions beyond "call emergency services now".

## 11. Diet and fitness plans

- Plans are written by the care team, not generated by the app on request. The app
  shows the currently active diet plan and fitness plan.
- A plan has an end date. When it passes, the plan expires overnight and disappears from
  the active view. A new plan comes from the care team.
- "I have no plan" or "my plan disappeared" → explain the above and hold so the care
  team can issue one.

## 12. Prescriptions and medications

- Prescriptions are created by the care provider from a photo of the prescription. The
  patient sees a prescription only after the provider confirms it, and receives it as a
  PDF in the chat with that provider.
- The **Prescriptions** area lists active medications. Only the care team can stop,
  pause or change a medication.
- Medication reminders arrive at fixed local times: 10:00 (morning), 15:00
  (afternoon), 21:00 (evening), 23:00 (night), in the profile timezone. Wrong reminder
  times almost always mean a wrong timezone on the profile.
- Questions about doses, side effects, or whether to take or skip a medicine are medical
  questions: redirect to the care team.

## 13. Check-ins and workouts

- Sleep, mood and symptom check-ins can be logged daily and show trends over time.
- Workouts can be logged manually or by voice, with type, duration and intensity.
  Workouts linked to a fitness plan session count towards that session.

## 14. AI health companion (chat and voice)

- The AI companion answers questions about the patient's own data (glucose, meals,
  sleep, activity, reports) and remembers preferences the patient shares. It is not a
  doctor and never gives medication doses.
- It is not technical support: for app problems, use this support chat.
- "The AI is unavailable" → either the feature is temporarily paused by the clinic or
  the patient sent many requests in a short time. Wait a few minutes and retry. If it
  stays unavailable for hours, hold.
- The companion may not remember something asked several messages ago; that is a known
  limitation, not a fault to report.
- Voice mode and WhatsApp reach the same companion where the clinic has enabled them.

## 15. Notifications

- The in-app notification list shows reminders, alerts and updates. Notification
  preferences in **Settings → Notifications** let the patient mute optional categories.
  Critical reminders (medication, prescriptions, safety alerts, follow-ups) cannot be
  muted and ignore quiet hours.
- No notifications at all → phone-level notification permission is off (section 5), or
  the app is not registered on this device (sign out and in again re-registers it), or
  battery optimisation is killing the app in the background.
- Some tips and insights are capped per day; not receiving one every day is normal.
- Patients inactive for a week or more may receive a few gentle reminder nudges.

## 16. Streaks, tasks and social features

- The app awards points and levels for daily tasks (logging meals, hitting step goals,
  taking medication, plan sessions). Tasks expire at the end of the day in the profile
  timezone; an expired task cannot be completed later.
- Streaks count consecutive active days. A streak freeze, when available, protects the
  streak for a missed day.
- Buddies are added with a buddy code; groups are joined with an invite code; challenges
  can be individual or group-based. An invite code that "does not work" may have been
  rotated by the group admin; ask for a fresh one.

## 17. How support tickets work

- A ticket is a conversation. The assistant replies first when no person from support
  has joined yet. Once a support person replies, the assistant stops and the person
  continues.
- Ticket states: open (waiting for support), pending (support has replied or is
  working on it), resolved, closed. The patient can close a ticket themselves. Writing
  again in a resolved or closed ticket reopens it.
- The support team is not available around the clock. When something needs a person,
  the assistant notes it on the ticket and the team replies in this same chat.

## 18. Always hand to a person (hold), never attempt

- Payments, package prices, renewals, refunds, invoices.
- Adding, changing or removing an assigned care provider or facility.
- Correcting, deleting or exporting logged data; deleting the account.
- Anything with an error code, a crash, or behaviour that contradicts this knowledge
  base (a possible bug).
- Complaints about staff, care, or the service.
- Requests for features that do not exist.
- Anything not covered here.

## 19. Known behaviours that are not bugs

- The day screen's glucose line falls back to finger-prick dots, then heart rate, when
  there is no CGM data for that day.
- The provider's patient summary is only visible to the care team, not in the patient
  app.
- Tapping some insight notifications opens the insight list rather than the chat.
- Documents uploaded by the care provider appear in the patient's list too, marked as
  uploaded by the provider.
