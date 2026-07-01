# AiHealth Dashboard — Helpline Knowledge Base

This is the reference the helpline agent uses to answer "how do I…/where is…" questions
from doctors, care providers, and admins using the AiHealth dashboard
(https://dashboard.aihealth.clinic/dashboard).

It has two parts:
- PART A — Structured reference (every section and where things live).
- PART B — Common Q&A (ready-made step-by-step answers).

If a question isn't covered, reason from PART A. Never invent a tab, button, or path
that isn't described here — if it's genuinely not here, say so and offer to find out.

---

# PART A — STRUCTURED REFERENCE

## Global layout
- Left sidebar (collapsible via the toggle at the bottom). Top-to-bottom:
  **Overview, Patients, Chats, Packages, Care Providers, Exercises, Gamification.**
- When collapsed it shows icons only; click the bottom toggle ("Collapse Sidebar"/expand) to show labels.
- Top-right shows the logged-in account (e.g. "AiHealth Admin").

## 1. Overview  (/dashboard/overview-v2)
The triage/home screen.
- Date-range selector (top right) + "Live" indicator.
- Stat cards: **Active Patients, Patients Enrolled, Meals Uploaded, At-Risk Patients**.
- CGM event cards: **Hyper Events, Hypo Events, High GV** — each shows severity (e.g. Low),
  patients flagged, peak/lowest glucose, max variability, longest event, risk level.
- **Patient Risk Records**: patients flagged by CGM triage. Filter tabs: All / Hyper / Hypo / High GV.
  Columns: Patient, Type, Metric, Duration, Last Event, CGM Trend, Severity. Has a patient search.
- **Activity & Nutrition** panel: tabs **Step Counts** / **Macro Nutrition**. Step Counts has a daily-steps
  threshold input and per-patient activity cards ("View Activity").

## 2. Patients  (/dashboard/patients)
List of all patients (paginated).
- Controls: **Search** (name/email/phone), **Filters**, **Columns** (show/hide columns),
  **Add New**, **Rows per page**, pagination.
- Columns: Name (+email, avatar), Gender, Phone Number, Age, Joining Date, Last Active, Actions (⋮).
- **Filters** popup: Age (Under 18, 18-25, 26-35, 36-45, 46-60, 60+); Gender; **Monitoring Method (SMBG Patient)**;
  Connected Apps (LibreView, Sinocare); Package (On Package / No Package). Clear Filters / Apply.
- Clicking a patient's **name only selects the row checkbox** — it does NOT open the patient.
  To open: row **⋮ (Actions) → View**.
- Row **⋮ Actions menu: View | Reports.**
- **Add New** → "Add Patient" multi-step form. Step 1 "Basic Info": First Name*, Last Name*, Email*,
  Phone Number* (country code + number), Date of Birth*, Gender*.

### Reports (the CGM / Diet / SMBG reports)
Open from: a patient row **⋮ → Reports**, OR the purple **Reports** button inside a patient's profile.
The popup has three tabs:
- **CGM**: pick **Start Date** + **End Date**, then **View Report**. This is the main glucose-statistics report
  over a period (time in range, average glucose, variability, highs/lows).
- **Diet**: dietary report (date range).
- **SMBG**: finger-prick glucose report. Quick ranges: **Today, Yesterday, Last 3 Days, This Week, This Month, Previous Month.**

### Patient detail page  (/dashboard/patients/{id}/view)
One long scrolling page. The buttons across the top are **toggle chips** that show/hide sections
(a blue check = shown; grey = hidden). **Documents and Notifications often start hidden** — click the chip to reveal them.
Top chips: **Day Report | Medications | Prescriptions | Documents | Proactive Insights | Notifications | Research.**

Left profile panel (top → bottom):
- Photo, name, last active.
- Action buttons: **Upload | Assign Package | Reports | Export**.
- **Care Providers** (assigned, with add).
- **Personal Information** (DOB, Age, Gender, Locale).
- **Measurements** (Height, Weight, Waist).
- **Contact Information** (Email, Phone).
- **Diet & LifeStyle** (sub-tabs Daily Activity / Alcohol Consumption / Smoking).
- **Medical History** (sub-tabs Diabetic History / Current Medication).
- **Connected Apps** (e.g. **LibreView** = CGM data source: shows ID, Last Sync, and **Sync Now** / **Unlink** buttons).
- **Permissions** (Notification, Health, Camera, Gallery, Storage — Enabled/Disabled).
- **Devices** (logged-in devices, with **Remove**).
- **Diet Plans** (**Create** button).

Main content sections (revealed by the chips):
- **Day Report**: a week date-strip (navigable) + sub-tabs:
  - **Meal Report**: kcal ring + Carbs/Protein/Fats/Fiber; "Meals (n)" cards (photo, meal type + time, dish,
    ingredients, macros, view + delete icons).
  - **Fitness Report**: "Daily Activity Snapshot" — Steps, Active Energy (kcal), Active Time (min),
    Peak hour, Longest rest, Avg session; "Steps by Hour" chart.
  - **CGM Report**: glucose line chart for the selected day.
- **Medications**: "What the patient is currently taking"; tabs Active / As Needed / Completed;
  **Add Prescription** button; expandable **Prescription History** (uploaded prescriptions & documents).
- **Prescriptions**: the medications/Add-Prescription area + Prescription History.
- **Documents**: "Uploaded reports, records, and AI-generated summaries." You **select up to 10 documents**
  (checkboxes); a "N selected" counter + **Chat** button let you ask AI questions about the selected documents.
  Empty state: "No documents found." Documents are added via the **Upload** button.
- **Proactive Insights**: AI-generated observations from recent health data; **Refresh** button;
  insight cards (badge, tag e.g. "Coaching celebration", timestamp, title + body, suggested follow-up).
- **Notifications**: feed with "N unread / N total", "Unread only" filter, Refresh, and category chips:
  All / Gamification / Med Lifecycle / Refill / Dose / Follow-up.
- **Research** (opens its own page /patients/{id}/research): a clinical-research module with tabs
  **Overview | Metabolic | Cardiovascular | Body Composition | Hormonal | Blood Biomarkers | Gut Microbiome | Fitness & Sleep.**
  Overview shows a Patient Health Overview (Time In Range, Daily Steps, Active/Day, Meals Logged, Weight),
  "Key Health Metrics at a Glance" cards (Glycemic Health; Cardiovascular Risk: Lp(a), Hs-CRP, ApoB, Triglycerides,
  LDL, HDL; Body Composition: Total Body Fat %, Skeletal Muscle Mass, RSMI, Android Fat %; Fitness & Recovery: VO2 Max),
  and "Priority Action Items".

### Patient action buttons (top-left of profile)
- **Upload** → "Upload Patient Data": choose a **Data Type** (LibreView Raw CSV, Linx Raw CSV, Sinocare Raw Excel,
  Reports, Other Medical Documents) then drag & drop the file. (This is how CGM raw data is imported and how
  documents for the Documents/Chat section are added — use Reports or Other Medical Documents.)
- **Assign Package** → "Patient Package Assignment": pick **Package** (required) + **Start Date** (required) → Submit.
- **Reports** → CGM/Diet/SMBG report popup (same as above).
- **Export** → export the patient's data.

### Built-in "Health Agent" (separate from this helpline bot)
A floating robot icon (bottom-right) opens **Health Agent** — an AI that answers questions about a patient's
**health DATA** (e.g. "glucose overview", "time in range", "meal impact"), with saved Threads per patient.
NOTE: that is different from this helpline bot. Health Agent = questions about patient data.
This helpline bot = questions about how to USE the dashboard.

## 3. Chats  (/dashboard/chats)
In-app messaging with patients/providers.
- Conversation list, **Search**, filters **Groups** and **Unread Only**, pin icon per chat.
- Open a conversation → thread view: header (name + close), messages with date separators, timestamps,
  read receipts; composer at the bottom (+ attachment, text box, emoji, send).

## 4. Packages  (/dashboard/packages)
Care-plan templates patients get assigned.
- Columns: Name, Status, Duration (days), Price, Type (PREMIUM/BASIC/TRIAL), Care Providers, Patients, Created At, Actions.
- Examples: WeightLoss (100d, PREMIUM), CGM-AiHealth (30d, PREMIUM), T1D (365d, BASIC), Gen (10d, TRIAL).
- **Add New** → "Add Package": Name*, Description, Package Type* (PREMIUM/BASIC/TRIAL), Duration (days)*, Price*.
- Row **⋮ Actions: Edit | Share Join Code** (each package has a join code patients/providers can use to join).
- KNOWN ISSUE: this page sometimes shows "This page couldn't load. A server error occurred." — click **Reload**.

## 5. Care Providers  (/dashboard/care-providers)
Directory of providers (doctors, dietitians, etc.).
- Columns: Name (+email), **Code** (their login/identifier code), Phone, Packages (assigned), Joining Date, Last Active, Actions.
- Row **⋮ Actions: Manage Permissions | Share Invite Code.**
- **Manage Permissions**: granular CRUD checkboxes (Read / Create / Update / Delete) per module —
  Meals, Reports, Fitness, Cgms, CareProviders (and more). This controls what a provider can access.
- **Add New** → "Add Care Provider" (2 steps): Personal Info (First Name*, Last Name*, Email*, Phone*, **Role*** dropdown);
  then Medical Info.

## 6. Exercises  (/dashboard/exercises)
Exercise library (~900+ exercises).
- Columns: Name, Category, Level, Equipment, Primary Muscles, Mechanic, Actions.
- **Search** (name/muscles/equipment), **Filters**, **Columns**, **Add New**.
- **Filters**: Level (Beginner/Intermediate/Expert); Category (Strength, Stretching, Plyometrics, Powerlifting,
  Olympic Weightlifting, Strongman, Cardio); Muscle (17 groups incl. Quadriceps, Hamstrings, Abdominals, Chest, …);
  Equipment (Barbell, Dumbbell, Body Only, Cable, Machine, Kettlebells, Bands, Medicine Ball, Exercise Ball, Foam Roll, E-Z Curl Bar).

## 7. Gamification  (/dashboard/gamification)
Patient engagement. Tabs:
- **Groups**: Name, Description, Invite Code, Members (x/cap), Status, Created; **Create Group**.
- **Challenges**: Title, Metric, Target, Duration, Period, Participants, XP Reward, Status; **Create Challenge**.
- **Achievements**: predefined badge catalog by category (e.g. Consistency, Nutrition) with tiers
  (Bronze/Silver/Gold/Platinum) and XP rewards.

---

# PART B — COMMON Q&A

**Q: Where do I find a patient's SMBG report?**
SMBG lives inside a patient's Reports, not as its own tab.
1. Open **Patients** in the left sidebar.
2. Find the patient (use the search bar — name, email, or phone).
3. Click the **⋮ (Actions)** on their row → **Reports** (or open the patient and click the purple **Reports** button).
4. In the popup, switch to the **SMBG** tab (next to CGM and Diet).
5. Pick a range — Today, Yesterday, Last 3 Days, This Week, This Month, or Previous Month — and the report opens.
Tip: to list only finger-prick patients, use Patients → Filters → Monitoring Method → SMBG Patient.

**Q: How do I see a patient's blood glucose statistics?**
Use the CGM report.
- Per day: open the patient (Patients → ⋮ → View) → Day Report → **CGM Report** sub-tab → pick the day.
- Over a period (time in range, average, variability): open the patient → **Reports** → **CGM** tab →
  set Start Date + End Date → **View Report**.
- Deeper analysis: the **Research** chip → Overview (Time In Range, Glycemic Health) and the Metabolic tab.
- Finger-prick instead of sensor: Reports → **SMBG** tab.

**Q: How do I assign a package to a patient?**
1. Open the patient (Patients → ⋮ → View).
2. Click the orange **Assign Package** button (top-left, next to Upload/Reports/Export).
3. In "Patient Package Assignment", pick the **Package** and a **Start Date**.
4. Click **Submit**.
Tip: packages come from the Packages section — if the one you want isn't listed, create it under Packages → Add New.
Patients can also self-join with a package's Join Code (Packages → package ⋮ → Share Join Code).

**Q: How do I chat with a patient's documents?**
1. Open the patient (Patients → ⋮ → View).
2. Make sure the **Documents** chip at the top is enabled (click it if it's greyed out).
3. Scroll to the **Documents** section.
4. Tick the documents you want (up to 10).
5. Click the **Chat** button to ask AI questions about them.
If it says "No documents found," upload some first: **Upload** button → Data Type = Reports or Other Medical Documents → drop the file.

**Q: A patient's CGM/glucose isn't syncing — what do I check?**
1. Open the patient (Patients → ⋮ → View).
2. In the left panel, scroll to **Connected Apps** (e.g. LibreView).
3. Check the **Last Sync** time; click **Sync Now** to force a sync, or **Unlink** and relink if needed.
Also confirm raw data was imported: **Upload** → LibreView Raw CSV / Linx Raw CSV / Sinocare Raw Excel.

**Q: How do I create a diet plan for a patient?**
Open the patient (Patients → ⋮ → View) → in the left panel scroll to the bottom to **Diet Plans** → click **Create**.

**Q: How do I add a prescription / medication for a patient?**
Open the patient → enable the **Medications** (or **Prescriptions**) chip → in the Medications section click **Add Prescription**.
Existing/uploaded ones are under **Prescription History**.

**Q: How do I give a care provider access to something (or restrict them)?**
Go to **Care Providers** → click the provider's **⋮** → **Manage Permissions** → toggle Read/Create/Update/Delete
for each module (Meals, Reports, Fitness, Cgms, CareProviders, …) → Save Changes.

**Q: How do I add a new patient / care provider?**
- Patient: **Patients → Add New** → fill Basic Info (name, email, phone, DOB, gender) and continue the steps.
- Care provider: **Care Providers → Add New** → Personal Info (name, email, phone, Role) → Medical Info.

**Q: How do I find all SMBG patients / patients without a package?**
Patients → **Filters** → Monitoring Method → SMBG Patient (or Package → No Package) → Apply.

**Q: Where do I see overall at-risk patients / glucose events across everyone?**
The **Overview** page: At-Risk Patients card, and the Hyper / Hypo / High GV event cards + Patient Risk Records triage.

**Q: How do I message a patient?**
**Chats** in the sidebar → pick the conversation (or search) → type in the composer at the bottom.

**Q: The Packages page won't load / shows a server error.**
That's a known intermittent issue — click **Reload** on the error screen. If it keeps failing, report it to the dev team.

**Q: I can't find a tab/section (e.g. Documents, Notifications) on the patient page.**
Those are toggle chips at the top of the patient page. If a section is missing, its chip is turned off (grey) —
click the chip (e.g. **Documents** or **Notifications**) to show it.

**Q: How do I export a patient's data?**
Open the patient → **Export** button (top-left of the profile).

**Q: How do I set up a group / challenge / achievement for engagement?**
**Gamification** in the sidebar → Groups tab (**Create Group**) / Challenges tab (**Create Challenge**) /
Achievements tab (predefined badge catalog).
