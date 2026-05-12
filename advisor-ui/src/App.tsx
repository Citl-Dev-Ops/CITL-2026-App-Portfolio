import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./App.css";
import {
  RTC_CAREER_CATEGORIES,
  type RtcProgram,
  type QuarterSlot,
  allPrograms,
  findProgram,
  SEASON_MONTHS,
} from "./rtcData";

// ─── Types ────────────────────────────────────────────────────────────────────

type Page = "search" | "catalog" | "planner" | "chat" | "studio";

type PlannerState = {
  program_count: number;
  transfer_equivalency_count: number;
  sbctc_mandate_count: number;
  institution_mandates: Record<string, number>;
  known_course_count: number;
  regex_corpus_record_count?: number;
  live_catalog_course_count?: number;
  live_catalog_generated_at?: string;
  live_catalog_term_codes?: string[];
  live_catalog_search_params?: Record<string, string>;
  live_catalog_delta?: { added_count?: number; removed_count?: number; changed_count?: number };
  last_transcript?: { file_name?: string; course_count?: number; parsed_at?: string };
};

type ProgramSummary = {
  program_id: string;
  program_name: string;
  award?: string | null;
  institution?: string | null;
  required_course_count: number;
  total_credits_required?: number | null;
};

type ProvisionStatus =
  | "high_likelihood"
  | "somewhat_likely"
  | "in_progress"
  | "dual_credit"
  | "waived_substituted"
  | "inconclusive"
  | "remedial"
  | "audit"
  | "repeated"
  | "not_eligible";

type TranscriptCourse = {
  course_code: string;
  course_key: string;
  subject?: string;
  catalog_number?: string;
  has_ampersand?: boolean;
  credits?: number | null;
  item_number?: string | null;
  grade?: string | null;
  year_hint?: number | null;
  institution_hint?: string | null;
  institution_class?: string | null;
  provision_status?: ProvisionStatus | null;
  provision_reason?: string | null;
};

type StudentSession = {
  student_slug: string;
  student_name: string;
  file_name?: string | null;
  parsed_at?: string | null;
  course_count: number;
  pinned: boolean;
  notes?: string;
  provision_summary?: Record<string, number>;
};

type Suggestion = {
  program_id: string;
  program_name: string;
  award?: string;
  match_ratio: number;
  matched_required: number;
  required_total: number;
  remaining_required: number;
  missing_preview: string[];
};

type Offering = {
  term?: string | null;
  course_code?: string | null;
  title?: string | null;
  credits?: number | null;
  status?: string | null;
  delivery?: string | null;
  instructor?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  days?: string | null;
  section?: string | null;
  class_number?: string | null;
  has_duplicates?: boolean;
  section_count?: number;
  source?: string;
};

type PathwayCourse = { course_code: string; course_key: string; credits: number; item_number?: string | null };
type PathwayTerm   = { term: string; planned_credits: number; courses: PathwayCourse[] };
type PaceScenario  = { credits_per_term: number; estimated_terms: number; estimated_tuition_total?: number | null };

type PlanResult = {
  error?: string;
  program?: { program_name?: string };
  progress?: {
    required_remaining?: number;
    remaining_required_credits_estimate?: number;
    hard_block_flags?: Array<{ description?: string }>;
  };
  decision?: { status?: string; hard_block_count?: number; approval_required_count?: number };
  compatibility?: { compatible_count?: number; incompatible_count?: number; unmapped_count?: number };
  pace?: { mode?: string; max_credits_per_term?: number };
  cost_inputs?: { tuition_per_credit?: number | null };
  pathway?: PathwayTerm[];
  remaining_after_horizon?: Array<{ course_code?: string }>;
  pace_scenarios?: Record<string, PaceScenario>;
};

type TranscriptMeta = { ocr_used?: boolean; extract_method?: string; ocr_warnings?: string[] };

type LiveCatalogStatus = {
  row_count?: number;
  generated_at?: string;
  term_codes?: string[];
  delta?: { added_count?: number; removed_count?: number; changed_count?: number };
  sync_profiles?: Array<{ name?: string; row_count?: number; term_codes?: string[] }>;
  sync_errors?: Array<{ name?: string; error?: string }>;
};

type PolicyQAResult = {
  policy_readiness_score?: number;
  severity_counts?: Record<string, number>;
  issues?: Array<{ severity?: string; scope?: string; message?: string }>;
};

type PathwayPrediction = {
  program_id?: string;
  program_name?: string;
  award?: string | null;
  match_ratio?: number;
  required_remaining?: number;
  remaining_required_credits_estimate?: number;
  estimated_terms_to_completion?: number;
  estimated_total_cost?: number | null;
  missing_course_preview?: string[];
};

type DeliveryFilter = "" | "in-person" | "online" | "hybrid";
type TimeFilter     = "" | "morning"   | "afternoon" | "evening";
type ScheduleFilter = "" | "day" | "evening";
type PaceFilter     = "" | "full_time" | "part_time";
type AwardTypeFilter = "" | "degree" | "certificate";

// ─── Helpers ──────────────────────────────────────────────────────────────────

const API_BASE = (
  import.meta.env.VITE_API_BASE
  || (typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1:8000")
).replace(/\/$/, "");

function err(e: unknown): string { return e instanceof Error ? e.message : String(e); }

function provisionLabel(status: ProvisionStatus): string {
  switch (status) {
    case "high_likelihood":    return "High Likelihood";
    case "somewhat_likely":    return "Somewhat Likely";
    case "in_progress":        return "In Progress";
    case "dual_credit":        return "Dual Credit / RS";
    case "waived_substituted": return "Waived / Substituted";
    case "inconclusive":       return "Inconclusive";
    case "remedial":           return "Remedial / Pre-College";
    case "audit":              return "Audit (No Credit)";
    case "repeated":           return "Repeated Course";
    case "not_eligible":       return "Not Eligible";
  }
}

const PROVISION_NEXT_STEPS: Record<ProvisionStatus, string[]> = {
  high_likelihood: [
    "Schedule an advisor appointment to confirm transfer credit.",
    "Bring your official sealed transcript to the appointment.",
    "Ask about SBCTC common course equivalencies (courses marked & transfer automatically).",
  ],
  somewhat_likely: [
    "Request an official transcript evaluation from the RTC Registrar.",
    "Ask your advisor whether an SBCTC or institutional equivalency applies.",
    "Bring the original course syllabus or catalog description if available.",
  ],
  in_progress: [
    "Wait for your final grade before requesting transfer evaluation.",
    "Provide an updated official transcript once the grade is posted.",
    "Contact the RTC Registrar's office to ask about provisional enrollment options.",
  ],
  dual_credit: [
    "Contact the RTC Registrar to confirm Running Start / dual-credit recognition.",
    "You may need a High School Authorization form or official HS transcript.",
    "Ask whether the course appears on your RTC record or requires a separate request.",
  ],
  waived_substituted: [
    "Speak with your academic advisor — bring supporting coursework documentation.",
    "A formal substitution or waiver petition may be required.",
    "Contact the academic department chair if a course equivalency is disputed.",
  ],
  inconclusive: [
    "Schedule an advisor appointment to discuss this course.",
    "Bring the original catalog description and any syllabi from that year.",
    "The Registrar may request additional documentation to evaluate credit.",
  ],
  remedial: [
    "Remedial / pre-college credits typically do not count toward degree requirements.",
    "Speak with your advisor about placement testing or retaking the course at college level.",
    "Ask whether the course fulfills any developmental education prerequisites at RTC.",
  ],
  audit: [
    "Audit enrollments do not earn credit toward degree requirements.",
    "If you completed equivalent content, ask your advisor about a credit-by-exam option.",
    "A letter-grade re-enrollment may be required to earn transfer credit.",
  ],
  repeated: [
    "Only the highest grade attempt typically counts toward transfer credit.",
    "Your advisor will confirm which attempt applies and how repeats affect your GPA.",
    "Bring documentation for all attempts when meeting with the Registrar.",
  ],
  not_eligible: [
    "Contact your advisor — an academic appeal or course substitution may be possible.",
    "Ask whether an equivalent RTC course satisfies the same requirement.",
    "The RTC Registrar can provide formal written evaluation of denied credits.",
  ],
};

function rtcQuarter(d: Date): string {
  const m = d.getMonth() + 1;
  const y = d.getFullYear();
  if (m >= 9) return `Fall ${y}`;
  if (m >= 7) return `Summer ${y}`;
  if (m >= 4) return `Spring ${y}`;
  return `Winter ${y}`;
}

function nextRtcQuarter(label: string): string {
  const [q, y] = label.split(" ");
  const yr = Number(y);
  const seq: Record<string, string> = { Winter: "Spring", Spring: "Summer", Summer: "Fall", Fall: "Winter" };
  const nextQ = seq[q] || "Spring";
  const nextY = nextQ === "Winter" ? yr + 1 : (q === "Fall" ? yr + 1 : yr);
  return `${nextQ} ${nextY}`;
}

function quarterToBeginTerm(label: string): string { return label.toUpperCase(); }

function timeOfDay(start_time?: string | null): TimeFilter | "" {
  if (!start_time) return "";
  const cleaned = start_time.replace(/\s+/g, "").toUpperCase();
  const amMatch = cleaned.match(/(\d{1,2}):?(\d{2})AM/);
  const pmMatch = cleaned.match(/(\d{1,2}):?(\d{2})PM/);
  const h24Match = cleaned.match(/^(\d{1,2}):?(\d{2})$/);
  let hour = -1;
  if (amMatch)      hour = Number(amMatch[1]) % 12;
  else if (pmMatch) hour = (Number(pmMatch[1]) % 12) + 12;
  else if (h24Match) hour = Number(h24Match[1]);
  if (hour < 0)  return "";
  if (hour < 12) return "morning";
  if (hour < 17) return "afternoon";
  return "evening";
}

function awardBucket(award?: string | null): "degree" | "certificate" | "other" {
  const a = (award || "").toLowerCase();
  if (a.includes("degree") || a.includes("associate") || a.includes("bachelor") || a.includes("aas") || a.includes("aa") || a.includes("as")) return "degree";
  if (a.includes("cert") || a.includes("apprentice")) return "certificate";
  return "other";
}

/** Determine next calendar year a given season starts, from today */
function nextSeasonYear(today: Date, season: QuarterSlot["season"]): number {
  const m = today.getMonth() + 1;
  const y = today.getFullYear();
  if (season === "Fall")   return m >= 9  ? y + 1 : y;
  if (season === "Winter") return m >= 1  ? (m < 9 ? y : y + 1) : y;
  if (season === "Spring") return m >= 4  ? (m < 9 ? y : y + 1) : y;
  return y; // Summer
}

/** Build a label like "Fall 2026" for a slot given the base year (first year of program) */
function slotLabel(slot: QuarterSlot, baseYear: number): string {
  // Year 1 Fall = baseYear, Year 1 Winter = baseYear+1 if Fall start
  // We track academic years: Fall->Winter->Spring = same academic year
  const acYear = baseYear + (slot.year - 1);
  if (slot.season === "Fall")   return `Fall ${acYear}`;
  if (slot.season === "Winter") return `Winter ${acYear + 1}`;
  if (slot.season === "Spring") return `Spring ${acYear + 1}`;
  return `Summer ${acYear + 1}`;
}

// ─── App ──────────────────────────────────────────────────────────────────────

export default function App() {
  const [page, setPage] = useState<Page>("search");

  // ── Quarter / term state ─────────────────────────────────────────────
  const now        = useMemo(() => new Date(), []);
  const currentQtr = useMemo(() => rtcQuarter(now), [now]);
  const nextQtr    = useMemo(() => nextRtcQuarter(currentQtr), [currentQtr]);

  // ── Planner & program state ──────────────────────────────────────────
  const [plannerState, setPlannerState]         = useState<PlannerState | null>(null);
  const [backendPrograms, setBackendPrograms]   = useState<ProgramSummary[]>([]);
  const [selectedProgramId, setSelectedProgramId] = useState("");

  // ── Static RTC data selection (career explorer) ──────────────────────
  const [selectedCategoryId, setSelectedCategoryId] = useState("");
  const [selectedRtcProgramId, setSelectedRtcProgramId] = useState("");
  const [calendarPaceMode, setCalendarPaceMode]       = useState<"full_time" | "part_time">("full_time");

  const selectedCategory = useMemo(
    () => RTC_CAREER_CATEGORIES.find((c) => c.id === selectedCategoryId) ?? null,
    [selectedCategoryId],
  );

  const selectedRtcProgram: RtcProgram | null = useMemo(() => {
    if (!selectedRtcProgramId) return null;
    return findProgram(selectedRtcProgramId) ?? null;
  }, [selectedRtcProgramId]);

  // Calendar: base year derived from PC date
  const calendarBaseYear = useMemo(() => {
    if (!selectedRtcProgram) return now.getFullYear();
    const firstSlot = selectedRtcProgram.quarterPlan[0];
    if (!firstSlot) return now.getFullYear();
    return nextSeasonYear(now, firstSlot.season);
  }, [selectedRtcProgram, now]);

  // Filter calendar by pace
  const visibleCalendarSlots = useMemo((): QuarterSlot[] => {
    if (!selectedRtcProgram) return [];
    if (calendarPaceMode === "full_time") return selectedRtcProgram.quarterPlan;
    // Part-time: stretch by moving 1 course per slot to next slot
    const stretched: QuarterSlot[] = [];
    const SEASONS: QuarterSlot["season"][] = ["Fall", "Winter", "Spring"];
    let sIdx = 0;
    let year = 1;
    let pending: string[] = selectedRtcProgram.quarterPlan.flatMap((s) => s.courses);
    while (pending.length > 0) {
      const take = Math.min(2, pending.length); // 2 courses per quarter part-time
      const batch = pending.splice(0, take);
      const season = SEASONS[sIdx % SEASONS.length];
      const totalCredits = batch.reduce((sum, code) => {
        const c = selectedRtcProgram.courses.find((x) => x.code === code);
        return sum + (c?.credits ?? 3);
      }, 0);
      stretched.push({ year, season, monthRange: SEASON_MONTHS[season], courses: batch, totalCredits });
      sIdx++;
      if (sIdx % SEASONS.length === 0) year++;
    }
    return stretched;
  }, [selectedRtcProgram, calendarPaceMode]);

  // Group calendar slots by year
  const calendarByYear = useMemo((): Map<number, QuarterSlot[]> => {
    const map = new Map<number, QuarterSlot[]>();
    visibleCalendarSlots.forEach((slot) => {
      const arr = map.get(slot.year) ?? [];
      arr.push(slot);
      map.set(slot.year, arr);
    });
    return map;
  }, [visibleCalendarSlots]);

  // ── Degree audit cascade selectors ──────────────────────────────────
  const [departments, setDepartments]       = useState<string[]>([]);
  const [selectedDept]                      = useState("");
  const [awardFilter]                       = useState<"" | "degree" | "certificate">("");

  // ── Transcript ───────────────────────────────────────────────────────
  const [transcriptCourses, setTranscriptCourses]   = useState<TranscriptCourse[]>([]);
  const [transcriptStatus, setTranscriptStatus]     = useState("No transcript loaded.");
  const [transcriptMeta, setTranscriptMeta]         = useState<TranscriptMeta | null>(null);
  const [transcriptStudentName, setTranscriptStudentName] = useState<string | null>(null);
  const [transcriptStudentSlug, setTranscriptStudentSlug] = useState<string | null>(null);

  // ── Student Sessions Repository ──────────────────────────────────────
  const [savedSessions, setSavedSessions]           = useState<StudentSession[]>([]);
  const [sessionsLoading, setSessionsLoading]       = useState(false);

  // ── Import status ────────────────────────────────────────────────────
  const [programImportStatus, setProgramImportStatus] = useState("");
  const [rulesImportStatus, setRulesImportStatus]     = useState("");

  // ── Suggestions / predictions / plan ────────────────────────────────
  const [suggestions, setSuggestions]               = useState<Suggestion[]>([]);
  const [, setPathwayPredictions] = useState<PathwayPrediction[]>([]);
  const [planResult, setPlanResult]                 = useState<PlanResult | null>(null);
  const [busy, setBusy]                             = useState(false);

  // ── Catalog browse ───────────────────────────────────────────────────
  const [browseSubject, setBrowseSubject]             = useState("");
  const [browseTerm, setBrowseTerm]                   = useState("");
  const [browseDelivery, setBrowseDelivery]           = useState<DeliveryFilter>("");
  const [browseOpenOnly, setBrowseOpenOnly]           = useState(false);
  const [browseTimeFilter, setBrowseTimeFilter]       = useState<TimeFilter>("");
  const [browseSchedule, setBrowseSchedule]           = useState<ScheduleFilter>("");
  const [browsePace, setBrowsePace]                   = useState<PaceFilter>("");
  const [browseProgramId, setBrowseProgramId]         = useState("");
  const [browseAwardType, setBrowseAwardType]         = useState<AwardTypeFilter>("");
  const [browseCategoryId, setBrowseCategoryId]       = useState("");
  const [browseResults, setBrowseResults]             = useState<Offering[]>([]);
  const [browseStatus, setBrowseStatus]               = useState("");
  const [selectedOffering, setSelectedOffering]       = useState<Offering | null>(null);

  // Legacy catalog search
  const [catalogQuery, setCatalogQuery] = useState("");
  const [offerings, setOfferings]       = useState<Offering[]>([]);

  // ── Live catalog admin ───────────────────────────────────────────────
  const [liveCatalogStatus, setLiveCatalogStatus]         = useState<LiveCatalogStatus | null>(null);
  const [liveCatalogMessage, setLiveCatalogMessage]       = useState("");
  const [liveInstitutionCode, setLiveInstitutionCode]     = useState("WA270");
  const [liveClassSearchUrl, setLiveClassSearchUrl]       = useState(
    "https://csprd.ctclink.us/psc/csprd/EMPLOYEE/SA/s/WEBLIB_HCX_CM.H_CLASS_SEARCH.FieldFormula.IScript_Main",
  );
  const [liveTermCodes, setLiveTermCodes]   = useState("");
  const [liveTermCount, setLiveTermCount]   = useState(3);
  const [liveSearchParamsJson, setLiveSearchParamsJson] = useState("{}");

  // ── Studio (admin) ───────────────────────────────────────────────────
  const [studioCategory, setStudioCategory]   = useState("");
  const [studioProgram, setStudioProgram]     = useState("");
  const [studioCourseFilter, setStudioCourseFilter] = useState("");
  const [studioScheduleFilter, setStudioScheduleFilter] = useState<ScheduleFilter>("");
  const [studioPaceFilter, setStudioPaceFilter]     = useState<PaceFilter>("");
  const [studioAwardFilter, setStudioAwardFilter]   = useState<AwardTypeFilter>("");
  const [studioPrereqFilter, setStudioPrereqFilter] = useState(""); // course code with prereqs
  const [regexMessage, setRegexMessage]             = useState("");
  const [policyQa, setPolicyQa]                     = useState<PolicyQAResult | null>(null);
  const [policyQaMessage, setPolicyQaMessage]       = useState("");
  const [adminPanelOpen, setAdminPanelOpen]         = useState(false);

  // ── LLM / Chat ───────────────────────────────────────────────────────
  const [ollamaModels, setOllamaModels]           = useState<string[]>([]);
  const [chatModel, setChatModel]                 = useState("qwen2.5:7b-instruct");
  const [chatInput, setChatInput]                 = useState("");
  const [chatMessages, setChatMessages]           = useState<{ role: "user" | "assistant"; text: string }[]>([
    { role: "assistant", text: "Hello! I'm your RTC Academic Advisor. Select a program or upload a transcript to get started, or ask me anything about courses and requirements." },
  ]);
  const [includeCatalogContext, setIncludeCatalogContext] = useState(true);
  const [useRegexChatContext, setUseRegexChatContext]     = useState(true);
  const chatBottomRef = useRef<HTMLDivElement | null>(null);

  // ── Planner page ─────────────────────────────────────────────────────
  const [beginTerm, setBeginTerm]               = useState(quarterToBeginTerm(nextQtr));
  const [institution, setInstitution]           = useState("Renton Technical College");
  const [paceMode, setPaceMode]                 = useState<"full_time" | "part_time" | "casual">("full_time");
  const [maxCredits, setMaxCredits]             = useState(15);
  const [horizonTerms, setHorizonTerms]         = useState(8);
  const [tuitionPerCredit, setTuitionPerCredit] = useState("0");
  const [feesPerTerm, setFeesPerTerm]           = useState(0);
  const [booksPerTerm, setBooksPerTerm]         = useState(0);
  const [includePaceScenarios, setIncludePaceScenarios] = useState(true);

  // Planner program browser (separate from audit)
  const [plannerCategoryId, setPlannerCategoryId]   = useState("");
  const [plannerRtcProgramId, setPlannerRtcProgramId] = useState("");
  const [plannerPaceMode, setPlannerPaceMode]         = useState<"full_time" | "part_time">("full_time");

  const plannerRtcProgram: RtcProgram | null = useMemo(
    () => (plannerRtcProgramId ? findProgram(plannerRtcProgramId) ?? null : null),
    [plannerRtcProgramId],
  );

  const plannerBaseYear = useMemo(() => {
    if (!plannerRtcProgram) return now.getFullYear();
    const firstSlot = plannerRtcProgram.quarterPlan[0];
    return firstSlot ? nextSeasonYear(now, firstSlot.season) : now.getFullYear();
  }, [plannerRtcProgram, now]);

  const plannerCalendarSlots = useMemo((): QuarterSlot[] => {
    if (!plannerRtcProgram) return [];
    if (plannerPaceMode === "full_time") return plannerRtcProgram.quarterPlan;
    // Part-time: 2 courses per quarter
    const SEASONS: QuarterSlot["season"][] = ["Fall", "Winter", "Spring"];
    const stretched: QuarterSlot[] = [];
    let sIdx = 0;
    let year = 1;
    let pending = plannerRtcProgram.quarterPlan.flatMap((s) => s.courses);
    while (pending.length > 0) {
      const take = Math.min(2, pending.length);
      const batch = pending.splice(0, take);
      const season = SEASONS[sIdx % SEASONS.length];
      const totalCredits = batch.reduce((sum, code) => {
        const c = plannerRtcProgram.courses.find((x) => x.code === code);
        return sum + (c?.credits ?? 3);
      }, 0);
      stretched.push({ year, season, monthRange: SEASON_MONTHS[season], courses: batch, totalCredits });
      sIdx++;
      if (sIdx % SEASONS.length === 0) year++;
    }
    return stretched;
  }, [plannerRtcProgram, plannerPaceMode]);

  const plannerCalendarByYear = useMemo((): Map<number, QuarterSlot[]> => {
    const map = new Map<number, QuarterSlot[]>();
    plannerCalendarSlots.forEach((slot) => {
      const arr = map.get(slot.year) ?? [];
      arr.push(slot);
      map.set(slot.year, arr);
    });
    return map;
  }, [plannerCalendarSlots]);

  // Studio filtered courses
  const studioProgramData = useMemo(() => {
    if (!studioProgram) return null;
    return findProgram(studioProgram) ?? null;
  }, [studioProgram]);

  const studioFilteredCourses = useMemo(() => {
    if (!studioProgramData) return [];
    let courses = [...studioProgramData.courses];
    if (studioCourseFilter) {
      const q = studioCourseFilter.toLowerCase();
      courses = courses.filter((c) => c.code.toLowerCase().includes(q) || c.title.toLowerCase().includes(q));
    }
    if (studioScheduleFilter) {
      courses = courses.filter((c) => (c.timeOptions ?? []).some((t) =>
        studioScheduleFilter === "day" ? (t === "day" || t === "online") : t === "evening"
      ));
    }
    if (studioPaceFilter === "full_time") {
      courses = courses.filter((c) => c.credits >= 4);
    } else if (studioPaceFilter === "part_time") {
      courses = courses.filter((c) => c.credits <= 3);
    }
    if (studioAwardFilter === "degree") {
      courses = courses.filter((c) => !c.isTransfer);
    } else if (studioAwardFilter === "certificate") {
      courses = courses.filter((c) => c.isCore);
    }
    if (studioPrereqFilter) {
      courses = courses.filter((c) => (c.prereqs ?? []).includes(studioPrereqFilter));
    }
    return courses;
  }, [studioProgramData, studioCourseFilter, studioScheduleFilter, studioPaceFilter, studioAwardFilter, studioPrereqFilter]);

  // ─────────────────────────────────────────────────────────────────────
  // Derived
  // ─────────────────────────────────────────────────────────────────────

  // selectedDept and awardFilter reserved for future cascade use
  void selectedDept; void awardFilter;

  const selectedBackendProgram = useMemo(
    () => backendPrograms.find((p) => p.program_id === selectedProgramId) ?? null,
    [backendPrograms, selectedProgramId],
  );

  const completionPct = useMemo(() => {
    if (!planResult?.progress || !selectedBackendProgram) return 0;
    const total = selectedBackendProgram.required_course_count || 1;
    const remaining = planResult.progress.required_remaining ?? total;
    return Math.round(Math.max(0, Math.min(100, ((total - remaining) / total) * 100)));
  }, [planResult, selectedBackendProgram]);

  const liveCatalogFreshness = useMemo(() => {
    const stamp = liveCatalogStatus?.generated_at || plannerState?.live_catalog_generated_at;
    if (!stamp) return "no live sync";
    const ms = Date.now() - new Date(stamp).getTime();
    const hours = Math.floor(ms / 3600000);
    if (hours < 1) return "updated <1h ago";
    if (hours < 24) return `updated ${hours}h ago`;
    return `updated ${Math.floor(hours / 24)}d ago`;
  }, [liveCatalogStatus?.generated_at, plannerState?.live_catalog_generated_at]);


  const paceHint = useMemo(() => {
    if (paceMode === "full_time") return "12–18 credits / term";
    if (paceMode === "part_time") return "6–11 credits / term";
    return "1–5 credits / term";
  }, [paceMode]);

  const visibleBrowseResults = useMemo(() => {
    let results = browseResults;
    if (browseTimeFilter) results = results.filter((r) => timeOfDay(r.start_time) === browseTimeFilter);
    return results;
  }, [browseResults, browseTimeFilter]);

  // Build unified program list for catalog dropdown (static + backend)
  const allProgramOptions = useMemo(() => {
    const staticProgs = allPrograms().map((p) => ({
      id: `rtc:${p.id}`,
      name: `${p.name} (${p.award})`,
      award: p.award,
      categoryId: p.categoryId,
      source: "static" as const,
    }));
    const backendProgs = backendPrograms.map((p) => ({
      id: p.program_id,
      name: `${p.program_name}${p.award ? ` (${p.award})` : ""}`,
      award: p.award ?? "",
      categoryId: "",
      source: "backend" as const,
    }));
    // Prefer backend if both exist
    const seen = new Set(backendProgs.map((p) => p.name.toLowerCase()));
    const dedupedStatic = staticProgs.filter((p) => !seen.has(p.name.toLowerCase()));
    return [...backendProgs, ...dedupedStatic];
  }, [backendPrograms]);

  // Filter by catalog filters for the catalog page
  const catalogFilteredPrograms = useMemo(() => {
    let list = allProgramOptions;
    if (browseCategoryId) list = list.filter((p) => p.categoryId === browseCategoryId);
    if (browseAwardType)  list = list.filter((p) => awardBucket(p.award) === browseAwardType);
    return list;
  }, [allProgramOptions, browseCategoryId, browseAwardType]);

  // Studio category programs
  const studioCategoryPrograms = useMemo(() => {
    if (!studioCategory) return allPrograms();
    const cat = RTC_CAREER_CATEGORIES.find((c) => c.id === studioCategory);
    return cat ? cat.programs : [];
  }, [studioCategory]);

  // Prereq options for studio filter
  const studioPrereqOptions = useMemo(() => {
    if (!studioProgramData) return [];
    const codes = new Set<string>();
    studioProgramData.courses.forEach((c) => (c.prereqs ?? []).forEach((p) => codes.add(p)));
    return Array.from(codes).sort();
  }, [studioProgramData]);

  // ─────────────────────────────────────────────────────────────────────
  // Data loaders
  // ─────────────────────────────────────────────────────────────────────

  const refreshPlannerState = useCallback(async () => {
    const [stateRes, programRes, liveRes] = await Promise.all([
      fetch(`${API_BASE}/planner/state`),
      fetch(`${API_BASE}/planner/programs`),
      fetch(`${API_BASE}/planner/live-catalog/status`),
    ]);
    if (stateRes.ok) setPlannerState(await stateRes.json());
    if (programRes.ok) {
      const d = await programRes.json();
      setBackendPrograms(d.programs || []);
      setSelectedProgramId((prev) => prev || d.programs?.[0]?.program_id || "");
    }
    if (liveRes.ok) setLiveCatalogStatus(await liveRes.json());
  }, []);

  const loadDepartments = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/planner/departments`);
      if (res.ok) { const d = await res.json(); setDepartments(d.departments || []); }
    } catch { /**/ }
  }, []);

  const loadOllamaModels = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/ollama/models`);
      if (res.ok) {
        const d = await res.json();
        if (d.models?.length) { setOllamaModels(d.models); setChatModel(d.models[0]); }
      }
    } catch { /**/ }
  }, []);

  const loadSessions = useCallback(async () => {
    setSessionsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/planner/sessions`);
      if (res.ok) {
        const d = await res.json();
        setSavedSessions(d.sessions || []);
      }
    } catch { /**/ }
    finally { setSessionsLoading(false); }
  }, []);

  useEffect(() => {
    refreshPlannerState().catch(() => undefined);
    loadDepartments().catch(() => undefined);
    loadOllamaModels().catch(() => undefined);
    loadSessions().catch(() => undefined);
  }, [refreshPlannerState, loadDepartments, loadOllamaModels, loadSessions]);

  // Restore transcript session from disk on first load
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/planner/transcript/session`);
        if (!res.ok) return;
        const d = await res.json();
        if (d.courses?.length) {
          setTranscriptCourses(d.courses);
          setTranscriptStudentName(d.student_name || null);
          setTranscriptStudentSlug(d.student_slug || null);
          setTranscriptStatus(
            `Session restored · ${d.courses.length} courses` +
            (d.student_name ? `  ·  ${d.student_name}` : "") +
            (d.file_name ? `  ·  ${d.file_name}` : "")
          );
        }
      } catch { /**/ }
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages.length, page]);

  // ─────────────────────────────────────────────────────────────────────
  // API actions
  // ─────────────────────────────────────────────────────────────────────

  async function uploadTranscript(file: File) {
    const form = new FormData();
    form.append("file", file);
    setTranscriptStatus("Parsing transcript…");
    setBusy(true);
    try {
      const res = await fetch(`${API_BASE}/planner/transcript/import`, { method: "POST", body: form });
      const d   = await res.json();
      if (!res.ok || !d?.ok) throw new Error(d?.detail || d?.error || res.statusText);
      setTranscriptCourses(d.courses || []);
      setTranscriptMeta({ ocr_used: !!d.ocr_used, extract_method: d.extract_method, ocr_warnings: d.ocr_warnings || [] });
      setTranscriptStudentName(d.student_name || null);
      setTranscriptStudentSlug(d.student_slug || null);
      const nameTag = d.student_name ? `  ·  ${d.student_name}` : "";
      setTranscriptStatus(`Loaded ${d.unique_course_count || 0} courses${nameTag}  ·  ${d.extract_method || ""}${d.ocr_used ? "  ·  OCR" : ""}`);
      await refreshPlannerState();
      await loadSessions();
    } catch (e) { setTranscriptStatus(`Import failed: ${err(e)}`); }
    finally { setBusy(false); }
  }

  async function importProgramPdf(files: FileList) {
    if (!files.length) return;
    const form = new FormData();
    Array.from(files).forEach((f) => form.append("files", f));
    setProgramImportStatus("Importing program PDF(s)…");
    setBusy(true);
    try {
      const res = await fetch(`${API_BASE}/planner/programs/import/pdf`, { method: "POST", body: form });
      const d   = await res.json();
      if (!res.ok || !d?.ok) throw new Error(d?.detail || d?.error || res.statusText);
      setProgramImportStatus(`Imported ${d.imported} program document(s).`);
      await refreshPlannerState();
      await loadDepartments();
    } catch (e) { setProgramImportStatus(`PDF import failed: ${err(e)}`); }
    finally { setBusy(false); }
  }

  async function importProgramJson(file: File) {
    setProgramImportStatus("Loading program JSON…");
    setBusy(true);
    try {
      const raw  = JSON.parse(await file.text());
      const body = Array.isArray(raw) ? { programs: raw, replace: false }
        : Array.isArray(raw?.programs) ? { programs: raw.programs, replace: false }
        : { programs: [raw], replace: false };
      const res = await fetch(`${API_BASE}/planner/programs/import/json`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const d = await res.json();
      if (!res.ok || !d?.ok) throw new Error(d?.detail || d?.error || res.statusText);
      setProgramImportStatus(`Imported ${d.imported} program(s).`);
      await refreshPlannerState();
      await loadDepartments();
    } catch (e) { setProgramImportStatus(`JSON import failed: ${err(e)}`); }
    finally { setBusy(false); }
  }

  async function importRulesJson(file: File) {
    setRulesImportStatus("Loading transfer rules…");
    setBusy(true);
    try {
      const raw   = JSON.parse(await file.text());
      const rules = raw?.rules ? raw.rules : raw;
      const res   = await fetch(`${API_BASE}/planner/transfer-rules/import/json`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rules, replace: false }),
      });
      const d = await res.json();
      if (!res.ok || !d?.ok) throw new Error(d?.detail || d?.error || res.statusText);
      setRulesImportStatus(`${d.equivalencies} equivalencies  ·  ${d.sbctc_mandates} SBCTC mandates`);
      await refreshPlannerState();
    } catch (e) { setRulesImportStatus(`Rules import failed: ${err(e)}`); }
    finally { setBusy(false); }
  }

  async function browseCatalog() {
    setBrowseStatus("Searching…");
    setBrowseResults([]);
    try {
      const params = new URLSearchParams();
      if (browseSubject)    params.set("subject",    browseSubject);
      if (browseTerm)       params.set("term",       browseTerm);
      if (browseDelivery)   params.set("delivery",   browseDelivery);
      if (browseOpenOnly)   params.set("open_only",  "true");
      // resolve rtc: prefix to program name
      if (browseProgramId && !browseProgramId.startsWith("rtc:")) params.set("program_id", browseProgramId);
      params.set("limit", "300");
      const res = await fetch(`${API_BASE}/offerings/browse?${params}`);
      const d   = await res.json();
      if (!res.ok) throw new Error(d?.detail || d?.error || res.statusText);
      setBrowseResults(d.results || []);
      setBrowseStatus(`${d.count || 0} offering${d.count === 1 ? "" : "s"} found`);
    } catch (e) { setBrowseStatus(`Search failed: ${err(e)}`); }
  }

  async function legacyCatalogSearch() {
    if (!catalogQuery.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/offerings?q=${encodeURIComponent(catalogQuery)}&limit=80`);
      const d   = await res.json();
      setOfferings(d.results || []);
    } catch { setOfferings([]); }
  }

  async function runSuggestions() {
    setBusy(true);
    try {
      const res = await fetch(`${API_BASE}/planner/suggest-programs`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transcript_courses: transcriptCourses, limit: 6 }),
      });
      const d = await res.json();
      if (!res.ok || !d?.ok) throw new Error(d?.detail || d?.error || res.statusText);
      setSuggestions(d.suggestions || []);
      if (!selectedProgramId && d.suggestions?.length) setSelectedProgramId(d.suggestions[0].program_id);
    } catch { setSuggestions([]); }
    finally { setBusy(false); }
  }

  async function runPathwayPredictions() {
    setBusy(true);
    try {
      const tp  = Number(tuitionPerCredit);
      const res = await fetch(`${API_BASE}/planner/predict-pathways`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          institution, begin_term: beginTerm, pace_mode: paceMode,
          transcript_courses: transcriptCourses, max_credits_per_term: maxCredits,
          horizon_terms: horizonTerms, candidate_limit: 8,
          tuition_per_credit: Number.isFinite(tp) && tp > 0 ? tp : null,
          fees_per_term: feesPerTerm, books_per_term: booksPerTerm,
        }),
      });
      const d = await res.json();
      if (!res.ok || !d?.ok) throw new Error(d?.detail || d?.error || res.statusText);
      setPathwayPredictions(d.predictions || []);
    } catch { setPathwayPredictions([]); }
    finally { setBusy(false); }
  }

  async function runPathwayPlan() {
    if (!selectedProgramId) return;
    setBusy(true);
    try {
      const tp  = Number(tuitionPerCredit);
      const res = await fetch(`${API_BASE}/planner/plan`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          institution, begin_term: beginTerm, pace_mode: paceMode,
          target_program_id: selectedProgramId, transcript_courses: transcriptCourses,
          max_credits_per_term: maxCredits, horizon_terms: horizonTerms,
          tuition_per_credit: Number.isFinite(tp) && tp > 0 ? tp : null,
          fees_per_term: feesPerTerm, books_per_term: booksPerTerm,
          include_pace_scenarios: includePaceScenarios,
        }),
      });
      const d = await res.json();
      if (!res.ok || !d?.ok) throw new Error(d?.detail || d?.error || res.statusText);
      setPlanResult(d);
    } catch (e) { setPlanResult({ error: err(e) }); }
    finally { setBusy(false); }
  }

  async function updateLiveCatalog() {
    setBusy(true);
    setLiveCatalogMessage("Pulling live catalog from ctcLink…");
    try {
      const parsed = liveTermCodes.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean);
      let sp: Record<string, string> = {};
      try { const o = JSON.parse(liveSearchParamsJson); if (o && typeof o === "object" && !Array.isArray(o)) sp = Object.fromEntries(Object.entries(o).map(([k, v]) => [k, String(v)])); } catch { /**/ }
      const res = await fetch(`${API_BASE}/planner/live-catalog/update`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          institution_code: liveInstitutionCode, class_search_main_url: liveClassSearchUrl,
          term_codes: parsed.length ? parsed : null, term_count: liveTermCount,
          enrl_stat: "O", subject: "", acad_career: "", search_params: sp, timeout_seconds: 60,
        }),
      });
      const d = await res.json();
      if (!res.ok || !d?.ok) throw new Error(d?.detail || d?.error || res.statusText);
      setLiveCatalogStatus(d);
      setLiveCatalogMessage(`Updated: ${d.row_count || 0} rows across ${(d.term_codes || []).length} term(s).`);
      await refreshPlannerState();
    } catch (e) { setLiveCatalogMessage(`Update failed: ${err(e)}`); }
    finally { setBusy(false); }
  }

  async function runPolicyQA() {
    setBusy(true);
    setPolicyQaMessage("Running policy QA checks…");
    try {
      const res = await fetch(`${API_BASE}/planner/policy/qa`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ include_all_institutions: true, include_regex_hints: true, regex_hint_limit: 20 }),
      });
      const d = await res.json();
      if (!res.ok || !d?.ok) throw new Error(d?.detail || d?.error || res.statusText);
      setPolicyQa(d);
      setPolicyQaMessage(`Score ${d.policy_readiness_score ?? 0}/100  ·  H:${d.severity_counts?.high ?? 0}  M:${d.severity_counts?.medium ?? 0}  L:${d.severity_counts?.low ?? 0}`);
    } catch (e) { setPolicyQaMessage(`QA failed: ${err(e)}`); }
    finally { setBusy(false); }
  }

  async function reindexRegexCorpus() {
    setBusy(true);
    setRegexMessage("Reindexing corpus…");
    try {
      const res = await fetch(`${API_BASE}/planner/regex-corpus/reindex`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ include_program_index: true, include_baseline_catalog: true, include_local_documents: true }),
      });
      const d = await res.json();
      if (!res.ok || !d?.ok) throw new Error(d?.detail || d?.error || res.statusText);
      setRegexMessage(`Corpus rebuilt: ${d.record_count || 0} records.`);
      await refreshPlannerState();
    } catch (e) { setRegexMessage(`Reindex failed: ${err(e)}`); }
    finally { setBusy(false); }
  }

  async function sendChat() {
    const prompt = chatInput.trim();
    if (!prompt) return;
    setChatInput("");
    setChatMessages((m) => [...m, { role: "user", text: prompt }]);
    const ctx = includeCatalogContext && selectedOffering
      ? `\n\n[Selected offering]\ncourse=${selectedOffering.course_code}\nterm=${selectedOffering.term}\ndelivery=${selectedOffering.delivery}`
      : "";
    setChatMessages((m) => [...m, { role: "assistant", text: "…" }]);
    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: prompt + ctx, model: chatModel, use_regex_context: useRegexChatContext, regex_context_limit: 8 }),
      });
      const d = await res.json();
      if (!res.ok || !d?.ok) throw new Error(d?.detail || d?.error || res.statusText);
      setChatMessages((m) => [...m.slice(0, -1), { role: "assistant", text: d.reply || "" }]);
    } catch (e) {
      setChatMessages((m) => [...m.slice(0, -1), { role: "assistant", text: `Error: ${err(e)}` }]);
    }
  }

  // ─────────────────────────────────────────────────────────────────────
  // UI helpers
  // ─────────────────────────────────────────────────────────────────────

  function statusColor(status?: string | null): string {
    const s = (status || "").toLowerCase();
    if (s.includes("open") || s === "o") return "status-open";
    if (s.includes("wait")) return "status-wait";
    return "status-closed";
  }

  // ─────────────────────────────────────────────────────────────────────
  // Sub-components (inline)
  // ─────────────────────────────────────────────────────────────────────

  /** Academic calendar for a given program and base year */
  function AcademicCalendar({ prog, byYear, labelFn }: {
    prog: RtcProgram;
    byYear: Map<number, QuarterSlot[]>;
    labelFn: (slot: QuarterSlot) => string;
  }) {
    return (
      <div className="cal-root">
        {Array.from(byYear.entries()).map(([year, slots]) => (
          <div key={year} className="cal-year-block">
            <div className="cal-year-label">
              Year {year}
              <span className="cal-year-sub">
                {labelFn(slots[0])} — {labelFn(slots[slots.length - 1])}
              </span>
            </div>
            <div className="cal-quarters">
              {slots.map((slot, si) => {
                const label = labelFn(slot);
                const isCurrentNext = label.toUpperCase() === currentQtr.toUpperCase() || label.toUpperCase() === nextQtr.toUpperCase();
                return (
                  <div key={si} className={`cal-quarter-tile${isCurrentNext ? " cal-tile-highlight" : ""}`}>
                    <div className="cal-tile-header">
                      <span className="cal-tile-season">{slot.season}</span>
                      <span className="cal-tile-year">{label.split(" ")[1]}</span>
                      {isCurrentNext && (
                        <span className="cal-tile-badge">
                          {label.toUpperCase() === currentQtr.toUpperCase() ? "NOW" : "NEXT"}
                        </span>
                      )}
                    </div>
                    <div className="cal-tile-months">{SEASON_MONTHS[slot.season]}</div>
                    <div className="cal-tile-courses">
                      {slot.courses.map((code) => {
                        const c = prog.courses.find((x) => x.code === code);
                        return (
                          <div key={code} className="cal-course-item">
                            <span className="cal-course-code">{code}</span>
                            <span className="cal-course-cr">{c?.credits ?? "?"} cr</span>
                          </div>
                        );
                      })}
                    </div>
                    <div className="cal-tile-footer">{slot.totalCredits ?? 0} cr total</div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    );
  }

  /** Career category selector grid */
  function CareerCategoryGrid({ value, onChange, size = "normal" }: {
    value: string;
    onChange: (id: string) => void;
    size?: "normal" | "compact";
  }) {
    return (
      <div className={`cat-grid${size === "compact" ? " cat-grid-compact" : ""}`}>
        {RTC_CAREER_CATEGORIES.map((cat) => (
          <button
            key={cat.id}
            className={`cat-card${value === cat.id ? " cat-card-active" : ""}`}
            onClick={() => onChange(value === cat.id ? "" : cat.id)}
          >
            <span className="cat-icon">{cat.icon}</span>
            <span className="cat-name">{cat.name}</span>
            <span className="cat-count">{cat.programs.length} programs</span>
          </button>
        ))}
      </div>
    );
  }

  // ─────────────────────────────────────────────────────────────────────
  // RENDER
  // ─────────────────────────────────────────────────────────────────────

  return (
    <div className="shell">

      {/* ── Top Bar ──────────────────────────────────────────────────── */}
      <header className="topbar">
        <div className="topbar-brand">
          <div className="topbar-logo">RTC</div>
          <div>
            <div className="topbar-name">Renton Technical College</div>
          </div>
        </div>
        <div className="topbar-sub">Academic Advisor</div>
        <div className="topbar-spacer" />
        <div className="topbar-status">
          {currentQtr} (current) · {nextQtr} (next) · {plannerState?.live_catalog_course_count ?? 0} live offerings
        </div>
      </header>

      {/* ── Sidebar ──────────────────────────────────────────────────── */}
      <nav className="sidebar">
        <div className="sidebar-section-label">Student</div>
        <button className={`navBtn ${page === "search" ? "active" : ""}`} onClick={() => setPage("search")}>
          <span className="navBtn-icon">🔍</span> Academic Search Tool
        </button>
        <button className={`navBtn ${page === "catalog" ? "active" : ""}`} onClick={() => setPage("catalog")}>
          <span className="navBtn-icon">📚</span> Course Catalog
        </button>
        <button className={`navBtn ${page === "planner" ? "active" : ""}`} onClick={() => setPage("planner")}>
          <span className="navBtn-icon">🗓</span> Quarter Planner
        </button>
        <button className={`navBtn ${page === "chat" ? "active" : ""}`} onClick={() => setPage("chat")}>
          <span className="navBtn-icon">💬</span> Advisor Chat
        </button>
        <div className="sidebar-section-label">System</div>
        <button className={`navBtn ${page === "studio" ? "active" : ""}`} onClick={() => setPage("studio")}>
          <span className="navBtn-icon">🎛️</span> Academic Advisor Studio
        </button>
        <div className="sidebar-footer">
          {RTC_CAREER_CATEGORIES.length} career areas · {allPrograms().length} programs
          {(plannerState?.last_transcript?.course_count ?? 0) > 0 && (
            <><br />Transcript: {plannerState!.last_transcript!.course_count} courses</>
          )}
        </div>
      </nav>

      {/* ── Main Workspace ───────────────────────────────────────────── */}
      <main className="workspace">

        {/* ════════════════════════════════════════════════════════════
            ACADEMIC SEARCH TOOL
        ════════════════════════════════════════════════════════════ */}
        {page === "search" && (
          <div className="stack">

            {/* Banner */}
            <div className="audit-banner">
              <div className="audit-banner-left">
                <h1>Academic Search Tool</h1>
                <p>Explore all career programs at RTC — select a career area, browse degrees and certificates, and see your quarter-by-quarter path to completion.</p>
              </div>
              <div className="rtc-badge">
                <strong>RTC</strong> · {currentQtr} · next: {nextQtr}
              </div>
            </div>

            {/* Career category selector */}
            <div className="card">
              <div className="card-title"><span className="card-title-icon">🎯</span> Step 1 — Choose a Career Area</div>
              <CareerCategoryGrid value={selectedCategoryId} onChange={(id) => { setSelectedCategoryId(id); setSelectedRtcProgramId(""); }} />
            </div>

            {/* Program selector (appears after category) */}
            {selectedCategory && (
              <div className="card">
                <div className="card-title">
                  <span className="card-title-icon">{selectedCategory.icon}</span>
                  Step 2 — Select a Program in {selectedCategory.name}
                </div>
                <p style={{ color: "var(--muted)", fontSize: "0.85rem", margin: "0 0 0.9rem" }}>{selectedCategory.description}</p>
                <div className="prog-list">
                  {selectedCategory.programs.map((prog) => (
                    <button
                      key={prog.id}
                      className={`prog-item${selectedRtcProgramId === prog.id ? " prog-item-active" : ""}`}
                      onClick={() => setSelectedRtcProgramId(prog.id)}
                    >
                      <div className="prog-item-top">
                        <span className="prog-item-name">{prog.name}</span>
                        <span className={`award-badge ${awardBucket(prog.award)}`}>{prog.award}</span>
                      </div>
                      <div className="prog-item-meta">
                        {prog.totalCredits} credits · {prog.years} year{prog.years > 1 ? "s" : ""}
                        <span className="prog-item-desc">{prog.description}</span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Calendar view (freeform — no transcript needed) */}
            {selectedRtcProgram && (
              <>
                <div className="card">
                  <div className="card-title"><span className="card-title-icon">🗓</span>
                    Academic Calendar — {selectedRtcProgram.name} ({selectedRtcProgram.award})
                    <span style={{ marginLeft: "auto", fontSize: "0.78rem", color: "var(--muted)", fontWeight: 400 }}>
                      {selectedRtcProgram.totalCredits} total credits · starting {calendarBaseYear}
                    </span>
                  </div>
                  <div className="inline-row" style={{ marginBottom: "0.85rem", gap: "0.5rem" }}>
                    <span style={{ fontSize: "0.78rem", color: "var(--muted)" }}>Pace:</span>
                    <button
                      className={`btn btn-sm ${calendarPaceMode === "full_time" ? "btn-primary" : ""}`}
                      onClick={() => setCalendarPaceMode("full_time")}
                    >Full-Time (12–18 cr)</button>
                    <button
                      className={`btn btn-sm ${calendarPaceMode === "part_time" ? "btn-primary" : ""}`}
                      onClick={() => setCalendarPaceMode("part_time")}
                    >Part-Time (6–9 cr)</button>
                  </div>
                  <AcademicCalendar
                    prog={selectedRtcProgram}
                    byYear={calendarByYear}
                    labelFn={(slot) => slotLabel(slot, calendarBaseYear)}
                  />
                </div>

                {/* Prerequisites */}
                {(selectedRtcProgram.prereqGroups ?? []).length > 0 && (
                  <div className="card">
                    <div className="card-title"><span className="card-title-icon">📋</span> Prerequisites &amp; Requirements</div>
                    <div className="prereq-grid">
                      {selectedRtcProgram.prereqGroups!.map((group, i) => (
                        <div key={i} className="prereq-group">
                          <div className="prereq-type">{group.type}</div>
                          <div className="prereq-desc">{group.description}</div>
                          <div className="prereq-credits">{group.minCredits} credits minimum</div>
                          <div className="prereq-options">
                            {group.options.map((code) => (
                              <span key={code} className="prereq-pill">{code}</span>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Course list */}
                <div className="card">
                  <div className="card-title"><span className="card-title-icon">📖</span> All Program Courses</div>
                  <div className="data-list-header" style={{ gridTemplateColumns: "7rem 1fr 3.5rem 5rem 6rem" }}>
                    <span>Code</span><span>Title</span><span>Cr</span><span>Options</span><span>Prerequisites</span>
                  </div>
                  <div style={{ maxHeight: 420, overflowY: "auto" }}>
                    {selectedRtcProgram.courses.filter((c) => c.isCore).map((c) => (
                      <div key={c.code} className="course-row" style={{ gridTemplateColumns: "7rem 1fr 3.5rem 5rem 6rem" }}>
                        <span className="course-code">{c.code}</span>
                        <span className="course-title">{c.title}{c.isTransfer ? <span className="transfer-tag">TRANSFER</span> : ""}</span>
                        <span className="course-credits">{c.credits}</span>
                        <span style={{ fontSize: "0.72rem", color: "var(--faint)" }}>
                          {(c.timeOptions ?? []).join(" · ")}
                        </span>
                        <span style={{ fontSize: "0.72rem", color: "var(--muted)", fontFamily: "var(--mono)" }}>
                          {(c.prereqs ?? []).join(", ") || "—"}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}

            {/* Degree audit (transcript-based) — shown after program selection */}
            {selectedRtcProgram && transcriptCourses.length === 0 && (
              <div className="card" style={{ borderColor: "var(--line-hi)" }}>
                <div className="card-title"><span className="card-title-icon">📄</span> Personalized Audit — Upload Transcript</div>
                <p style={{ color: "var(--muted)", fontSize: "0.85rem", margin: "0 0 0.7rem" }}>
                  Upload your transcript to see exactly which courses you still need and a personalized quarter-by-quarter plan.
                </p>
                <div className="inline-row">
                  <input
                    type="file"
                    accept=".pdf,.json,.csv,.tsv,.txt"
                    style={{ flex: 1 }}
                    onChange={(e) => e.target.files?.[0] && uploadTranscript(e.target.files[0])}
                  />
                </div>
              </div>
            )}

            {/* Plan result if transcript loaded */}
            {planResult && !planResult.error && (
              <div className="audit-grid">
                <div className="progress-sidebar">
                  <div className="progress-ring-wrap">
                    <svg width="120" height="120" viewBox="0 0 120 120">
                      <circle cx="60" cy="60" r="50" fill="none" stroke="var(--line)" strokeWidth="10" />
                      <circle
                        cx="60" cy="60" r="50" fill="none"
                        stroke={completionPct >= 80 ? "var(--success)" : completionPct >= 40 ? "var(--gold)" : "var(--accent)"}
                        strokeWidth="10"
                        strokeDasharray={`${(completionPct / 100) * 314} 314`}
                        strokeLinecap="round"
                        transform="rotate(-90 60 60)"
                      />
                      <text x="60" y="56" className="ring-label ring-pct">{completionPct}%</text>
                      <text x="60" y="70" className="ring-label ring-sub">complete</text>
                    </svg>
                    <div className="progress-meta">
                      <div className="progress-meta-row"><span>Required remaining</span><strong>{planResult.progress?.required_remaining ?? "—"}</strong></div>
                      <div className="progress-meta-row"><span>Credits remaining</span><strong>{planResult.progress?.remaining_required_credits_estimate ?? "—"}</strong></div>
                      <div className="progress-meta-row"><span>Terms planned</span><strong>{(planResult.pathway || []).length}</strong></div>
                      <div className="progress-meta-row">
                        <span>Status</span>
                        <strong style={{ color: planResult.decision?.hard_block_count ? "var(--danger)" : "var(--success)" }}>
                          {planResult.decision?.status || "OK"}
                        </strong>
                      </div>
                    </div>
                  </div>
                  {planResult.pace_scenarios && Object.keys(planResult.pace_scenarios).length > 0 && (
                    <div className="card" style={{ padding: "0.75rem" }}>
                      <div className="card-title" style={{ marginBottom: "0.55rem" }}>Pace Scenarios</div>
                      {Object.entries(planResult.pace_scenarios).map(([mode, sc]) => (
                        <div key={mode} className="pace-card">
                          <div className="pace-label">{mode}</div>
                          <div className="pace-value">{sc.estimated_terms} terms</div>
                          <div className="pace-sub">{sc.credits_per_term} cr/term{sc.estimated_tuition_total ? `  ·  $${sc.estimated_tuition_total.toLocaleString()}` : ""}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div className="stack">
                  <div className="card">
                    <div className="card-title"><span className="card-title-icon">🗓</span> Your Quarter-by-Quarter Plan — {planResult.program?.program_name}</div>
                    {(planResult.pathway || []).length === 0 ? (
                      <p style={{ color: "var(--muted)", fontSize: "0.85rem" }}>No pathway generated. Check program selection and transcript.</p>
                    ) : (
                      <div className="pathway-grid">
                        {(planResult.pathway || []).map((term) => (
                          <div key={term.term} className="pathway-term-card">
                            <div className="pathway-term-header">{term.term}<span className="pathway-term-credits">{term.planned_credits} cr</span></div>
                            {(term.courses || []).map((c) => (
                              <div key={`${term.term}-${c.course_key}`} className="pathway-course-item">
                                <span className="pathway-course-code">{c.course_code}</span>
                                <span className="pathway-course-cr">{c.credits} cr</span>
                              </div>
                            ))}
                          </div>
                        ))}
                      </div>
                    )}
                    {(planResult.remaining_after_horizon?.length ?? 0) > 0 && (
                      <div className="alert alert-warn" style={{ marginTop: "0.75rem" }}>
                        {planResult.remaining_after_horizon!.length} course(s) beyond planning horizon.
                      </div>
                    )}
                  </div>
                  {suggestions.length > 0 && (
                    <div className="card">
                      <div className="card-title"><span className="card-title-icon">💡</span> Suggested Matches Based on Transcript</div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
                        {suggestions.slice(0, 6).map((s) => (
                          <div key={s.program_id} className={`suggestion-chip ${selectedProgramId === s.program_id ? "selected" : ""}`}
                            onClick={() => setSelectedProgramId(s.program_id)}>
                            <span>{s.program_name}</span>
                            <span className="chip-match">{Math.round(s.match_ratio * 100)}%</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
            {planResult?.error && <div className="alert alert-danger">{planResult.error}</div>}

            {transcriptCourses.length > 0 && (
              <div className="btn-row">
                <div className="filter-group" style={{ minWidth: 240 }}>
                  <div className="filter-label">Select Backend Program for Audit</div>
                  <select value={selectedProgramId} onChange={(e) => setSelectedProgramId(e.target.value)}>
                    <option value="">— choose a program —</option>
                    {backendPrograms.map((p) => (
                      <option key={p.program_id} value={p.program_id}>
                        {p.program_name}{p.award ? ` (${p.award})` : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <button className="btn btn-primary" disabled={busy || !selectedProgramId || transcriptCourses.length === 0} onClick={runPathwayPlan}>
                  Build Audit →
                </button>
                <button className="btn" disabled={busy || transcriptCourses.length === 0} onClick={runSuggestions}>Suggest Programs</button>
                <button className="btn" disabled={busy || transcriptCourses.length === 0} onClick={runPathwayPredictions}>Predict Alternatives</button>
              </div>
            )}

            {/* ── Transcript Provision Table ─────────────────────────── */}
            {transcriptCourses.length > 0 && (
              <div className="card" style={{ marginTop: "1rem" }}>
                <div className="card-title">
                  <span className="card-title-icon">🎓</span>
                  Detected Transcript Courses — Provisional Eligibility Assessment
                </div>
                <p className="provision-disclaimer">
                  All courses are <strong>provisionally assessed</strong> based on parsed transcript data.
                  Final eligibility is determined only during an official advisor degree audit.
                  Hover over any status badge for details on why a course received its rating.
                </p>
                <div className="provision-legend">
                  {(["high_likelihood","somewhat_likely","in_progress","dual_credit","waived_substituted","inconclusive","remedial","audit","repeated","not_eligible"] as ProvisionStatus[]).map(s => (
                    <span key={s} className={`provision-badge provision-badge--${s}`}>
                      {provisionLabel(s)}
                    </span>
                  ))}
                </div>
                <div className="provision-table-wrap">
                  <table className="provision-table">
                    <thead>
                      <tr>
                        <th>Course</th>
                        <th>Grade</th>
                        <th>Credits</th>
                        <th>Year</th>
                        <th>Institution</th>
                        <th>Provisional Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {transcriptCourses.map((c, i) => {
                        const status: ProvisionStatus = (c.provision_status as ProvisionStatus) ?? "inconclusive";
                        return (
                          <tr key={`${c.course_key}-${i}`} className={`provision-row provision-row--${status}`}>
                            <td className="provision-course-code">
                              {c.course_code}
                              {c.has_ampersand && <span className="provision-transfer-tag" title="Official WA transfer designation">&amp;</span>}
                            </td>
                            <td className="provision-grade">{c.grade ?? <span className="provision-nd">—</span>}</td>
                            <td className="provision-credits">{c.credits != null ? `${c.credits} cr` : <span className="provision-nd">—</span>}</td>
                            <td className="provision-year">{c.year_hint ?? <span className="provision-nd">—</span>}</td>
                            <td className="provision-institution" title={c.institution_hint ?? ""}>
                              {c.institution_hint
                                ? (c.institution_hint.length > 28 ? c.institution_hint.slice(0, 26) + "…" : c.institution_hint)
                                : <span className="provision-nd">Unknown</span>}
                            </td>
                            <td>
                              <span
                                className={`provision-badge provision-badge--${status}`}
                                title={c.provision_reason ?? ""}
                                aria-label={c.provision_reason ?? provisionLabel(status)}
                              >
                                {provisionLabel(status)}
                                <span className="provision-tooltip">{c.provision_reason ?? provisionLabel(status)}</span>
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="provision-footer">
                  Hover the status badge on any row for the specific reason. Bring your original transcript to your advisor appointment for official evaluation.
                </p>

                {/* Further Steps per RTC Policy */}
                {(() => {
                  const statusesPresent = Array.from(new Set(transcriptCourses.map(c => (c.provision_status as ProvisionStatus) ?? "inconclusive")));
                  return (
                    <div className="provision-steps-wrap">
                      <div className="provision-steps-title">Further Steps per RTC Policy</div>
                      {statusesPresent.map(s => (
                        <div key={s} className={`provision-steps-block provision-steps-block--${s}`}>
                          <span className={`provision-badge provision-badge--${s}`} style={{ marginBottom: "0.4rem" }}>
                            {provisionLabel(s)}
                          </span>
                          <ul className="provision-steps-list">
                            {PROVISION_NEXT_STEPS[s].map((step, idx) => (
                              <li key={idx}>{step}</li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                  );
                })()}
              </div>
            )}
          </div>
        )}

        {/* ════════════════════════════════════════════════════════════
            COURSE CATALOG
        ════════════════════════════════════════════════════════════ */}
        {page === "catalog" && (
          <div className="stack">
            <div className="page-header">
              <div>
                <h2 className="page-title">Course Catalog</h2>
                <p className="page-subtitle">Browse offerings by career area, degree/certificate program, term, delivery mode, and schedule</p>
              </div>
            </div>

            {/* Primary filter: Career Area → Program */}
            <div className="card">
              <div className="card-title"><span className="card-title-icon">🎯</span> Find by Career Area &amp; Program</div>
              <div className="cascade-row" style={{ flexWrap: "wrap" }}>
                <div className="filter-group" style={{ minWidth: 180 }}>
                  <div className="filter-label">Career Area</div>
                  <select value={browseCategoryId} onChange={(e) => { setBrowseCategoryId(e.target.value); setBrowseProgramId(""); }}>
                    <option value="">All career areas</option>
                    {RTC_CAREER_CATEGORIES.map((cat) => (
                      <option key={cat.id} value={cat.id}>{cat.icon} {cat.name}</option>
                    ))}
                  </select>
                </div>
                <div className="cascade-arrow">›</div>
                <div className="filter-group" style={{ minWidth: 260, flex: 1 }}>
                  <div className="filter-label">Degree / Certificate Program</div>
                  <select value={browseProgramId} onChange={(e) => setBrowseProgramId(e.target.value)}>
                    <option value="">All programs</option>
                    {catalogFilteredPrograms.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>
                <div className="cascade-arrow">›</div>
                <div className="filter-group" style={{ minWidth: 150 }}>
                  <div className="filter-label">Award Type</div>
                  <select value={browseAwardType} onChange={(e) => setBrowseAwardType(e.target.value as AwardTypeFilter)}>
                    <option value="">Degree &amp; Certificate</option>
                    <option value="degree">Degrees (AAS, AA, AS…)</option>
                    <option value="certificate">Certificates</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Secondary filters */}
            <div className="filter-bar">
              <div className="filter-group">
                <div className="filter-label">Department / Subject</div>
                <select value={browseSubject} onChange={(e) => setBrowseSubject(e.target.value)}>
                  <option value="">All subjects</option>
                  {departments.map((d) => <option key={d} value={d}>{d}</option>)}
                  {/* Add static departments from RTC data */}
                  {["AUTO", "BAKE", "BUSA", "ACCT", "CARP", "CIS", "CSEC", "CULN", "DA", "ELET", "HVAC", "MA", "MATH", "NETW", "NURS", "OFAD", "PHRM", "WEBD", "WELD"].filter(
                    (d) => !departments.includes(d)
                  ).map((d) => <option key={d} value={d}>{d}</option>)}
                </select>
              </div>

              <div className="filter-group">
                <div className="filter-label">Term</div>
                <div style={{ display: "flex", gap: "0.3rem", alignItems: "center" }}>
                  <span
                    className={`term-pill ${browseTerm === currentQtr.toUpperCase() ? "active" : ""}`}
                    onClick={() => setBrowseTerm(browseTerm === currentQtr.toUpperCase() ? "" : currentQtr.toUpperCase())}
                    style={{ fontSize: "0.72rem", padding: "0.22rem 0.6rem" }}
                  >{currentQtr}</span>
                  <span
                    className={`term-pill gold-pill ${browseTerm === nextQtr.toUpperCase() ? "active" : ""}`}
                    onClick={() => setBrowseTerm(browseTerm === nextQtr.toUpperCase() ? "" : nextQtr.toUpperCase())}
                    style={{ fontSize: "0.72rem", padding: "0.22rem 0.6rem" }}
                  >{nextQtr}</span>
                  <input
                    type="text"
                    value={browseTerm}
                    onChange={(e) => setBrowseTerm(e.target.value.toUpperCase())}
                    placeholder="or type term…"
                    style={{ width: 120, fontSize: "0.8rem", padding: "0.28rem 0.55rem" }}
                  />
                </div>
              </div>

              <div className="filter-group">
                <div className="filter-label">Schedule</div>
                <select value={browseSchedule} onChange={(e) => setBrowseSchedule(e.target.value as ScheduleFilter)}>
                  <option value="">Day &amp; Evening</option>
                  <option value="day">Day (before 5pm)</option>
                  <option value="evening">Evening (after 5pm)</option>
                </select>
              </div>

              <div className="filter-group">
                <div className="filter-label">Delivery</div>
                <select value={browseDelivery} onChange={(e) => setBrowseDelivery(e.target.value as DeliveryFilter)}>
                  <option value="">Any delivery</option>
                  <option value="in-person">In-Person</option>
                  <option value="online">Online</option>
                  <option value="hybrid">Hybrid</option>
                </select>
              </div>

              <div className="filter-group">
                <div className="filter-label">Pace</div>
                <select value={browsePace} onChange={(e) => setBrowsePace(e.target.value as PaceFilter)}>
                  <option value="">Full &amp; Part Time</option>
                  <option value="full_time">Full-Time (≥4 cr)</option>
                  <option value="part_time">Part-Time (≤3 cr)</option>
                </select>
              </div>

              <div className="filter-group">
                <div className="filter-label">Time of Day</div>
                <select value={browseTimeFilter} onChange={(e) => setBrowseTimeFilter(e.target.value as TimeFilter)}>
                  <option value="">Any time</option>
                  <option value="morning">Morning (before noon)</option>
                  <option value="afternoon">Afternoon (noon–5pm)</option>
                  <option value="evening">Evening (after 5pm)</option>
                </select>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem", justifyContent: "flex-end" }}>
                <label className="checkbox-row">
                  <input type="checkbox" checked={browseOpenOnly} onChange={(e) => setBrowseOpenOnly(e.target.checked)} />
                  Open sections only
                </label>
                <button className="btn btn-primary" onClick={browseCatalog}>Search Live Catalog</button>
              </div>
            </div>

            {browseStatus && (
              <div className="status-line">{browseStatus}{browseTimeFilter ? ` (filtered to ${browseTimeFilter}: ${visibleBrowseResults.length})` : ""}</div>
            )}

            <div className="grid-2">
              <div className="card" style={{ padding: "0.5rem" }}>
                <div className="data-list-header" style={{ gridTemplateColumns: "6.5rem 1fr 3.5rem 4.5rem 4.5rem" }}>
                  <span>Code</span><span>Title</span><span>Cr</span><span>Delivery</span><span>Status</span>
                </div>
                <div style={{ maxHeight: 500, overflowY: "auto" }}>
                  {visibleBrowseResults.length === 0 && (
                    <div style={{ padding: "1.5rem", color: "var(--faint)", textAlign: "center", fontSize: "0.85rem" }}>
                      {browseStatus ? "No results match current filters." : "Select filters above and click Search Live Catalog."}
                    </div>
                  )}
                  {visibleBrowseResults.map((o, i) => (
                    <div
                      key={i}
                      className={`course-row ${selectedOffering === o ? "selected" : ""} ${o.has_duplicates ? "dup-warn" : ""}`}
                      onClick={() => setSelectedOffering(o)}
                    >
                      <span className="course-code">{o.course_code || "—"}</span>
                      <span className="course-title" title={o.title || ""}>{o.title || "—"}</span>
                      <span className="course-credits">{o.credits ?? "—"}</span>
                      <span className="course-delivery">{o.delivery || "—"}</span>
                      <span className={`course-status ${statusColor(o.status)}`}>
                        {o.status || "—"}
                        {o.has_duplicates && <span className="dup-badge" title={`${o.section_count} section(s)`}>{o.section_count}§</span>}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="stack" style={{ gap: "0.75rem" }}>
                {selectedOffering ? (
                  <div className="detail-panel">
                    <div style={{ fontSize: "1.05rem", fontWeight: 600, marginBottom: "0.6rem", color: "var(--text)" }}>
                      {selectedOffering.course_code} — {selectedOffering.title}
                    </div>
                    {[
                      ["Term",      selectedOffering.term],
                      ["Credits",   selectedOffering.credits],
                      ["Status",    selectedOffering.status],
                      ["Delivery",  selectedOffering.delivery],
                      ["Instructor",selectedOffering.instructor],
                      ["Days",      selectedOffering.days],
                      ["Start",     selectedOffering.start_time],
                      ["End",       selectedOffering.end_time],
                      ["Section",   selectedOffering.section],
                      ["Class #",   selectedOffering.class_number],
                      ["Source",    selectedOffering.source],
                    ].filter(([, v]) => v).map(([k, v]) => (
                      <div key={String(k)} className="detail-row">
                        <span className="detail-key">{k}</span>
                        <span className="detail-value">{String(v)}</span>
                      </div>
                    ))}
                    {selectedOffering.start_time && (
                      <div style={{ marginTop: "0.5rem" }}>
                        <span className="time-badge">🕐 {timeOfDay(selectedOffering.start_time) || "unknown"}</span>
                      </div>
                    )}
                    <button
                      className="btn btn-primary btn-sm"
                      style={{ marginTop: "0.75rem" }}
                      onClick={() => { setPage("chat"); setChatMessages((m) => [...m, { role: "user", text: `Tell me about ${selectedOffering.course_code}` }]); }}
                    >
                      Ask Advisor about this course
                    </button>
                  </div>
                ) : (
                  <div className="card" style={{ color: "var(--faint)", fontSize: "0.85rem" }}>
                    Select a course from the results to see full details.
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ════════════════════════════════════════════════════════════
            QUARTER PLANNER
        ════════════════════════════════════════════════════════════ */}
        {page === "planner" && (
          <div className="stack">
            <div className="page-header">
              <div>
                <h2 className="page-title">Quarter Planner</h2>
                <p className="page-subtitle">Browse programs and build your quarter-by-quarter academic plan with prerequisites</p>
              </div>
            </div>

            {/* ── Student Sessions Repository ──────────────────────── */}
            <div className="card sessions-card">
              <div className="card-title">
                <span className="card-title-icon">👤</span>
                Student Session Repository
                <button
                  className="btn btn-ghost btn-sm"
                  style={{ marginLeft: "auto" }}
                  onClick={loadSessions}
                  disabled={sessionsLoading}
                >
                  {sessionsLoading ? "…" : "↻ Refresh"}
                </button>
              </div>

              {/* Active transcript banner */}
              {transcriptCourses.length > 0 && (
                <div className="sessions-active-banner">
                  <span className="sessions-active-name">{transcriptStudentName || "Unknown Student"}</span>
                  <span className="sessions-active-meta">
                    {transcriptCourses.length} courses loaded
                    {transcriptStudentSlug && (
                      <button
                        className="btn btn-sm"
                        style={{ marginLeft: "0.5rem" }}
                        onClick={async () => {
                          if (!transcriptStudentSlug) return;
                          const pinned = savedSessions.find(s => s.student_slug === transcriptStudentSlug)?.pinned;
                          await fetch(`${API_BASE}/planner/sessions/${transcriptStudentSlug}/pin`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ pinned: !pinned }),
                          });
                          await loadSessions();
                        }}
                      >
                        {savedSessions.find(s => s.student_slug === transcriptStudentSlug)?.pinned ? "Unpin Demo" : "Pin as Demo"}
                      </button>
                    )}
                  </span>
                </div>
              )}

              {/* Sessions list */}
              {savedSessions.length === 0 ? (
                <p className="sessions-empty">No saved sessions yet. Upload a transcript to create the first one.</p>
              ) : (
                <div className="sessions-list">
                  {savedSessions.map((s) => (
                    <div
                      key={s.student_slug}
                      className={`sessions-row ${s.pinned ? "sessions-row--pinned" : ""} ${transcriptStudentSlug === s.student_slug ? "sessions-row--active" : ""}`}
                    >
                      <div className="sessions-row-left">
                        <span className="sessions-name">{s.student_name}</span>
                        {s.pinned && <span className="sessions-pin-badge">DEMO</span>}
                        <span className="sessions-meta">
                          {s.course_count} courses
                          {s.file_name && ` · ${s.file_name.slice(0, 32)}${s.file_name.length > 32 ? "…" : ""}`}
                          {s.parsed_at && ` · ${new Date(s.parsed_at).toLocaleDateString()}`}
                        </span>
                      </div>
                      <div className="sessions-row-actions">
                        <button
                          className="btn btn-sm btn-primary"
                          disabled={transcriptStudentSlug === s.student_slug}
                          onClick={async () => {
                            const res = await fetch(`${API_BASE}/planner/sessions/${s.student_slug}/load`, { method: "POST" });
                            if (res.ok) {
                              const d = await res.json();
                              // Fetch full session data to populate transcript
                              const full = await fetch(`${API_BASE}/planner/sessions/${s.student_slug}`);
                              if (full.ok) {
                                const fd = await full.json();
                                setTranscriptCourses(fd.courses || []);
                                setTranscriptStudentName(fd.student_name || null);
                                setTranscriptStudentSlug(fd.student_slug || null);
                                setTranscriptStatus(`Loaded ${fd.courses?.length || 0} courses · ${d.student_name || s.student_name}`);
                              }
                            }
                          }}
                        >
                          {transcriptStudentSlug === s.student_slug ? "Active" : "Load"}
                        </button>
                        <button
                          className="btn btn-sm"
                          title={s.pinned ? "Unpin from demo" : "Pin as stakeholder demo"}
                          onClick={async () => {
                            await fetch(`${API_BASE}/planner/sessions/${s.student_slug}/pin`, {
                              method: "POST",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify({ pinned: !s.pinned }),
                            });
                            await loadSessions();
                          }}
                        >
                          {s.pinned ? "Unpin" : "Pin Demo"}
                        </button>
                        <button
                          className="btn btn-sm"
                          style={{ color: "var(--danger)" }}
                          title="Delete session"
                          onClick={async () => {
                            if (!confirm(`Delete session for ${s.student_name}?`)) return;
                            await fetch(`${API_BASE}/planner/sessions/${s.student_slug}`, { method: "DELETE" });
                            await loadSessions();
                          }}
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <p className="sessions-footer">
                Upload a transcript PDF to auto-detect the student name and create a persistent session.
                Pinned sessions appear at the top for stakeholder demos.
              </p>
            </div>

            <div className="grid-planner">
              {/* LEFT: Program browser + calendar + prereqs */}
              <div className="stack">
                <div className="card">
                  <div className="card-title"><span className="card-title-icon">🎓</span> Program Browser</div>

                  <div className="form-group">
                    <div className="form-label">Career Area</div>
                    <select value={plannerCategoryId} onChange={(e) => { setPlannerCategoryId(e.target.value); setPlannerRtcProgramId(""); }}>
                      <option value="">— Select a career area —</option>
                      {RTC_CAREER_CATEGORIES.map((cat) => (
                        <option key={cat.id} value={cat.id}>{cat.icon} {cat.name}</option>
                      ))}
                    </select>
                  </div>

                  {plannerCategoryId && (
                    <div className="form-group">
                      <div className="form-label">Degree / Certificate</div>
                      <select value={plannerRtcProgramId} onChange={(e) => setPlannerRtcProgramId(e.target.value)}>
                        <option value="">— Select a program —</option>
                        {(RTC_CAREER_CATEGORIES.find((c) => c.id === plannerCategoryId)?.programs ?? []).map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name} ({p.award}) — {p.totalCredits} cr
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  {plannerRtcProgram && (
                    <>
                      <div className="inline-row" style={{ marginBottom: "0.75rem" }}>
                        <span style={{ fontSize: "0.78rem", color: "var(--muted)" }}>Credits per quarter:</span>
                        <button
                          className={`btn btn-sm ${plannerPaceMode === "full_time" ? "btn-primary" : ""}`}
                          onClick={() => setPlannerPaceMode("full_time")}
                        >Full-Time 12–18</button>
                        <button
                          className={`btn btn-sm ${plannerPaceMode === "part_time" ? "btn-primary" : ""}`}
                          onClick={() => setPlannerPaceMode("part_time")}
                        >Part-Time 6–9</button>
                        <input
                          type="number"
                          value={maxCredits}
                          onChange={(e) => setMaxCredits(Number(e.target.value || 15))}
                          style={{ width: 70, fontSize: "0.8rem" }}
                          placeholder="custom"
                          title="Custom credits per term"
                        />
                      </div>
                    </>
                  )}
                </div>

                {/* Calendar */}
                {plannerRtcProgram && plannerCalendarByYear.size > 0 && (
                  <div className="card">
                    <div className="card-title">
                      <span className="card-title-icon">📅</span>
                      {plannerRtcProgram.name} — {plannerPaceMode === "full_time" ? "Full-Time" : "Part-Time"} Plan
                      <span style={{ marginLeft: "auto", fontSize: "0.78rem", color: "var(--muted)", fontWeight: 400 }}>
                        starting {plannerBaseYear}
                      </span>
                    </div>
                    <AcademicCalendar
                      prog={plannerRtcProgram}
                      byYear={plannerCalendarByYear}
                      labelFn={(slot) => slotLabel(slot, plannerBaseYear)}
                    />
                  </div>
                )}

                {/* Prerequisites */}
                {plannerRtcProgram && (plannerRtcProgram.prereqGroups ?? []).length > 0 && (
                  <div className="card">
                    <div className="card-title"><span className="card-title-icon">📋</span> Required Prerequisites</div>
                    <div className="prereq-grid">
                      {plannerRtcProgram.prereqGroups!.map((group, i) => (
                        <div key={i} className="prereq-group">
                          <div className="prereq-type">{group.type}</div>
                          <div className="prereq-desc">{group.description}</div>
                          <div className="prereq-credits">{group.minCredits} credits minimum</div>
                          <div className="prereq-options">
                            {group.options.map((code) => (
                              <span key={code} className="prereq-pill">{code}</span>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* RIGHT: Student Intent + Transcript */}
              <div className="stack">
                <div className="card">
                  <div className="card-title"><span className="card-title-icon">🎯</span> Student Intent</div>

                  <div className="form-group">
                    <div className="form-label">Institution</div>
                    <input type="text" value={institution} onChange={(e) => setInstitution(e.target.value)} />
                  </div>

                  <div className="form-group">
                    <div className="form-label">Begin Term</div>
                    <div className="term-pills" style={{ marginBottom: "0.4rem" }}>
                      <span className={`term-pill ${beginTerm === quarterToBeginTerm(currentQtr) ? "active" : ""}`}
                        onClick={() => setBeginTerm(quarterToBeginTerm(currentQtr))}>Current — {currentQtr}</span>
                      <span className={`term-pill gold-pill ${beginTerm === quarterToBeginTerm(nextQtr) ? "active" : ""}`}
                        onClick={() => setBeginTerm(quarterToBeginTerm(nextQtr))}>Next — {nextQtr}</span>
                    </div>
                    <select value={beginTerm} onChange={(e) => setBeginTerm(e.target.value)}>
                      {["Winter", "Spring", "Summer", "Fall"].flatMap((q) =>
                        [2026, 2027, 2028].map((y) => `${q.toUpperCase()} ${y}`)
                      ).map((t) => <option key={t} value={t}>{t}</option>)}
                    </select>
                  </div>

                  <div className="form-group">
                    <div className="form-label">Pacing — {paceHint}</div>
                    <select value={paceMode} onChange={(e) => {
                      const m = e.target.value as typeof paceMode;
                      setPaceMode(m);
                      setMaxCredits(m === "full_time" ? 15 : m === "part_time" ? 8 : 4);
                    }}>
                      <option value="full_time">Full-Time (12–18 cr/term)</option>
                      <option value="part_time">Part-Time (6–11 cr/term)</option>
                      <option value="casual">Casual (1–5 cr/term)</option>
                    </select>
                  </div>

                  <div className="grid-2" style={{ gap: "0.5rem" }}>
                    <div className="form-group">
                      <div className="form-label">Credits / Term</div>
                      <input type="number" value={maxCredits} onChange={(e) => setMaxCredits(Number(e.target.value || 15))} />
                    </div>
                    <div className="form-group">
                      <div className="form-label">Horizon (terms)</div>
                      <input type="number" value={horizonTerms} onChange={(e) => setHorizonTerms(Number(e.target.value || 8))} />
                    </div>
                    <div className="form-group">
                      <div className="form-label">Tuition / Credit ($)</div>
                      <input type="number" value={tuitionPerCredit} onChange={(e) => setTuitionPerCredit(e.target.value)} />
                    </div>
                    <div className="form-group">
                      <div className="form-label">Fees / Term ($)</div>
                      <input type="number" value={feesPerTerm} onChange={(e) => setFeesPerTerm(Number(e.target.value || 0))} />
                    </div>
                    <div className="form-group">
                      <div className="form-label">Books / Term ($)</div>
                      <input type="number" value={booksPerTerm} onChange={(e) => setBooksPerTerm(Number(e.target.value || 0))} />
                    </div>
                  </div>

                  <label className="checkbox-row">
                    <input type="checkbox" checked={includePaceScenarios} onChange={(e) => setIncludePaceScenarios(e.target.checked)} />
                    Include full/part/casual cost comparison
                  </label>
                </div>

                {/* Transcript */}
                <div className="card">
                  <div className="card-title"><span className="card-title-icon">📄</span> Transcript Indexing</div>
                  <input type="file" accept=".pdf,.json,.csv,.tsv,.txt"
                    onChange={(e) => e.target.files?.[0] && uploadTranscript(e.target.files[0])} />
                  <div className="status-line" style={{ marginTop: "0.4rem" }}>{transcriptStatus}</div>
                  {transcriptCourses.length > 0 && (
                    <div className="status-line">
                      {transcriptCourses.length} courses indexed
                      {transcriptMeta?.ocr_used && <span style={{ color: "var(--warn)", marginLeft: "0.5rem" }}>OCR used</span>}
                    </div>
                  )}
                </div>

                {/* Backend program selector for audit */}
                <div className="card">
                  <div className="card-title"><span className="card-title-icon">🖥️</span> Advisor Backend Plan</div>
                  <div className="form-group">
                    <div className="form-label">Backend Program</div>
                    <select value={selectedProgramId} onChange={(e) => setSelectedProgramId(e.target.value)}>
                      <option value="">— select backend program —</option>
                      {backendPrograms.map((p) => <option key={p.program_id} value={p.program_id}>{p.program_name}{p.award ? ` (${p.award})` : ""}</option>)}
                    </select>
                  </div>
                  <div className="btn-row">
                    <button className="btn btn-primary" disabled={busy || !selectedProgramId || transcriptCourses.length === 0} onClick={runPathwayPlan}>
                      Build Quarter Plan
                    </button>
                    <button className="btn" disabled={busy || transcriptCourses.length === 0} onClick={runSuggestions}>Suggest Paths</button>
                    <button className="btn" disabled={busy || transcriptCourses.length === 0} onClick={runPathwayPredictions}>Predict Alternatives</button>
                  </div>
                  {programImportStatus && <div className="status-line" style={{ marginTop: "0.4rem" }}>{programImportStatus}</div>}
                </div>
              </div>
            </div>

            {/* Plan result */}
            {planResult && (
              <div className="grid-2">
                <div className="card">
                  <div className="card-title">Quarter Pathway</div>
                  {planResult.error ? (
                    <div className="alert alert-danger">{planResult.error}</div>
                  ) : (
                    <>
                      <div className="status-line">{planResult.program?.program_name}  ·  {planResult.progress?.required_remaining} remaining  ·  {planResult.decision?.status}</div>
                      {(planResult.pathway || []).map((term) => (
                        <div key={term.term} style={{ borderTop: "1px solid var(--line)", paddingTop: "0.55rem", marginTop: "0.55rem" }}>
                          <div style={{ fontWeight: 600, color: "var(--accent)", fontSize: "0.83rem", marginBottom: "0.3rem" }}>
                            {term.term} — {term.planned_credits} credits
                          </div>
                          {(term.courses || []).map((c) => (
                            <div key={c.course_key} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem", padding: "0.15rem 0", color: "var(--muted)" }}>
                              <span style={{ fontFamily: "var(--mono)", color: "var(--accent)" }}>{c.course_code}</span>
                              <span>{c.credits} cr</span>
                            </div>
                          ))}
                        </div>
                      ))}
                    </>
                  )}
                </div>
                <div className="card">
                  <div className="card-title">Suggested Paths</div>
                  {suggestions.length === 0
                    ? <div style={{ color: "var(--faint)", fontSize: "0.85rem" }}>Run "Suggest Paths" above.</div>
                    : suggestions.slice(0, 5).map((s) => (
                      <div key={s.program_id} className={`suggestion-chip ${selectedProgramId === s.program_id ? "selected" : ""}`}
                        style={{ marginBottom: "0.4rem", display: "flex" }}
                        onClick={() => setSelectedProgramId(s.program_id)}>
                        <span style={{ flex: 1 }}>{s.program_name}</span>
                        <span className="chip-match">{Math.round(s.match_ratio * 100)}%  ·  {s.remaining_required} left</span>
                      </div>
                    ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ════════════════════════════════════════════════════════════
            ADVISOR CHAT
        ════════════════════════════════════════════════════════════ */}
        {page === "chat" && (
          <div className="chat-layout">
            <div className="card" style={{ padding: "0.6rem 0.9rem" }}>
              <div className="inline-row">
                <div className="filter-group" style={{ minWidth: 220 }}>
                  <div className="filter-label">Ollama Model</div>
                  <select value={chatModel} onChange={(e) => setChatModel(e.target.value)}>
                    {ollamaModels.length === 0
                      ? <option value={chatModel}>{chatModel}</option>
                      : ollamaModels.map((m) => <option key={m} value={m}>{m}</option>)}
                  </select>
                </div>
                <label className="checkbox-row">
                  <input type="checkbox" checked={useRegexChatContext} onChange={(e) => setUseRegexChatContext(e.target.checked)} />
                  Attach corpus context
                </label>
                <label className="checkbox-row">
                  <input type="checkbox" checked={includeCatalogContext} onChange={(e) => setIncludeCatalogContext(e.target.checked)} />
                  Attach selected offering
                </label>
                {selectedOffering && (
                  <span style={{ fontSize: "0.78rem", color: "var(--gold)" }}>📎 {selectedOffering.course_code}</span>
                )}
                <button className="btn btn-ghost btn-sm" onClick={loadOllamaModels}>↻ Refresh models</button>
                {transcriptCourses.length > 0 && (
                  <span className="chat-transcript-indicator">
                    Transcript context active · {transcriptCourses.length} courses
                  </span>
                )}
              </div>
            </div>

            <div className="chat-log">
              {chatMessages.map((m, i) => (
                <div key={i} className={`chat-msg ${m.role} ${m.role === "assistant" && m.text === "…" ? "thinking" : ""}`}>
                  {m.text}
                </div>
              ))}
              <div ref={chatBottomRef} />
            </div>

            <div className="chat-input-bar">
              <textarea
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                placeholder="Ask about requirements, programs, transfer credits, schedules…"
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); } }}
                rows={2}
              />
              <button className="btn btn-primary" onClick={sendChat} style={{ alignSelf: "flex-end", height: 50 }}>Send</button>
            </div>
          </div>
        )}

        {/* ════════════════════════════════════════════════════════════
            ACADEMIC ADVISOR STUDIO
        ════════════════════════════════════════════════════════════ */}
        {page === "studio" && (
          <div className="stack">
            <div className="page-header">
              <div>
                <h2 className="page-title">Academic Advisor Studio</h2>
                <p className="page-subtitle">Browse program course requirements, search by career area, and manage system data</p>
              </div>
            </div>

            {/* Main studio: career hierarchy → program → course browser */}
            <div className="card">
              <div className="card-title"><span className="card-title-icon">🎓</span> Step 1 — Select Career Area</div>
              <CareerCategoryGrid value={studioCategory} onChange={(id) => { setStudioCategory(id); setStudioProgram(""); }} size="compact" />
            </div>

            {studioCategory && (
              <div className="card">
                <div className="card-title"><span className="card-title-icon">📋</span> Step 2 — Select Program</div>
                <div className="prog-list prog-list-compact">
                  {studioCategoryPrograms.map((prog) => (
                    <button
                      key={prog.id}
                      className={`prog-item${studioProgram === prog.id ? " prog-item-active" : ""}`}
                      onClick={() => { setStudioProgram(prog.id); setStudioCourseFilter(""); setStudioPrereqFilter(""); }}
                    >
                      <div className="prog-item-top">
                        <span className="prog-item-name">{prog.name}</span>
                        <span className={`award-badge ${awardBucket(prog.award)}`}>{prog.award}</span>
                      </div>
                      <div className="prog-item-meta">
                        {prog.totalCredits} credits · {prog.years} yr · {prog.courses.filter((c) => c.isCore).length} core courses
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {studioProgramData && (
              <>
                {/* Course filter toolbar */}
                <div className="filter-bar">
                  <div className="filter-group" style={{ minWidth: 160 }}>
                    <div className="filter-label">Course Search</div>
                    <input
                      type="text"
                      value={studioCourseFilter}
                      onChange={(e) => setStudioCourseFilter(e.target.value)}
                      placeholder="Code or title…"
                    />
                  </div>

                  <div className="filter-group">
                    <div className="filter-label">Day / Night</div>
                    <select value={studioScheduleFilter} onChange={(e) => setStudioScheduleFilter(e.target.value as ScheduleFilter)}>
                      <option value="">Day &amp; Night</option>
                      <option value="day">Day (incl. online)</option>
                      <option value="evening">Evening</option>
                    </select>
                  </div>

                  <div className="filter-group">
                    <div className="filter-label">Full / Part Time</div>
                    <select value={studioPaceFilter} onChange={(e) => setStudioPaceFilter(e.target.value as PaceFilter)}>
                      <option value="">Any load</option>
                      <option value="full_time">Full-Time (≥4 cr/course)</option>
                      <option value="part_time">Part-Time (≤3 cr/course)</option>
                    </select>
                  </div>

                  <div className="filter-group">
                    <div className="filter-label">Degree / Certificate</div>
                    <select value={studioAwardFilter} onChange={(e) => setStudioAwardFilter(e.target.value as AwardTypeFilter)}>
                      <option value="">All courses</option>
                      <option value="degree">Degree core courses</option>
                      <option value="certificate">Certificate core courses</option>
                    </select>
                  </div>

                  <div className="filter-group">
                    <div className="filter-label">Requires Prerequisite</div>
                    <select value={studioPrereqFilter} onChange={(e) => setStudioPrereqFilter(e.target.value)}>
                      <option value="">Any (no prereq filter)</option>
                      {studioPrereqOptions.map((code) => (
                        <option key={code} value={code}>Requires {code}</option>
                      ))}
                    </select>
                  </div>

                  <div style={{ display: "flex", alignItems: "flex-end" }}>
                    <button className="btn btn-ghost btn-sm" onClick={() => { setStudioCourseFilter(""); setStudioScheduleFilter(""); setStudioPaceFilter(""); setStudioAwardFilter(""); setStudioPrereqFilter(""); }}>
                      Clear Filters
                    </button>
                  </div>
                </div>

                {/* Course results */}
                <div className="card" style={{ padding: "0.5rem" }}>
                  <div className="card-title" style={{ padding: "0.3rem 0.5rem" }}>
                    {studioProgramData.name} — {studioFilteredCourses.length} course{studioFilteredCourses.length !== 1 ? "s" : ""}
                    <span style={{ marginLeft: "auto", fontSize: "0.77rem", color: "var(--muted)", fontWeight: 400 }}>
                      {studioProgramData.award} · {studioProgramData.totalCredits} total credits
                    </span>
                  </div>
                  <div className="data-list-header" style={{ gridTemplateColumns: "7rem 1fr 3rem 5rem 6rem 5rem" }}>
                    <span>Code</span>
                    <span>Title</span>
                    <span>Cr</span>
                    <span>Schedule</span>
                    <span>Prerequisites</span>
                    <span>Type</span>
                  </div>
                  <div style={{ maxHeight: 500, overflowY: "auto" }}>
                    {studioFilteredCourses.length === 0 && (
                      <div style={{ padding: "1.5rem", color: "var(--faint)", textAlign: "center", fontSize: "0.85rem" }}>
                        No courses match the current filters.
                      </div>
                    )}
                    {studioFilteredCourses.map((c) => (
                      <div key={c.code} className="course-row" style={{ gridTemplateColumns: "7rem 1fr 3rem 5rem 6rem 5rem" }}>
                        <span className="course-code" style={{ fontFamily: "var(--mono)" }}>{c.code}</span>
                        <span className="course-title">
                          {c.title}
                          {c.isTransfer && <span className="transfer-tag">TRANSFER</span>}
                        </span>
                        <span className="course-credits">{c.credits}</span>
                        <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
                          {(c.timeOptions ?? []).join(", ") || "—"}
                        </span>
                        <span style={{ fontSize: "0.72rem", color: "var(--muted)", fontFamily: "var(--mono)" }}>
                          {(c.prereqs ?? []).join(", ") || "—"}
                        </span>
                        <span>
                          {c.isCore && <span className="req-pill complete" style={{ fontSize: "0.65rem" }}>core</span>}
                          {c.isTransfer && <span className="req-pill partial" style={{ fontSize: "0.65rem" }}>transfer</span>}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Quarter plan for selected program */}
                <div className="card">
                  <div className="card-title"><span className="card-title-icon">📅</span> Standard Quarter Plan — {studioProgramData.name}</div>
                  <div className="cal-root">
                    {Array.from((() => {
                      const m = new Map<number, QuarterSlot[]>();
                      studioProgramData.quarterPlan.forEach((s) => { const a = m.get(s.year) ?? []; a.push(s); m.set(s.year, a); });
                      return m;
                    })().entries()).map(([year, slots]) => (
                      <div key={year} className="cal-year-block">
                        <div className="cal-year-label">Year {year}</div>
                        <div className="cal-quarters">
                          {slots.map((slot, si) => (
                            <div key={si} className="cal-quarter-tile">
                              <div className="cal-tile-header">
                                <span className="cal-tile-season">{slot.season}</span>
                              </div>
                              <div className="cal-tile-months">{SEASON_MONTHS[slot.season]}</div>
                              <div className="cal-tile-courses">
                                {slot.courses.map((code) => {
                                  const c = studioProgramData.courses.find((x) => x.code === code);
                                  return (
                                    <div key={code} className="cal-course-item">
                                      <span className="cal-course-code">{code}</span>
                                      <span className="cal-course-cr">{c?.credits ?? "?"} cr</span>
                                    </div>
                                  );
                                })}
                              </div>
                              <div className="cal-tile-footer">{slot.totalCredits ?? 0} cr</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}

            {/* ── Subordinated admin tools ──────────────────────────────────── */}
            <button
              className="btn btn-ghost"
              style={{ alignSelf: "flex-start", marginTop: "0.5rem" }}
              onClick={() => setAdminPanelOpen((v) => !v)}
            >
              {adminPanelOpen ? "▲ Hide" : "▼ Show"} Data Management &amp; System Tools
            </button>

            {adminPanelOpen && (
              <>
                <div className="kpiGrid">
                  <div className="kpiCard">
                    <div className="kpiLabel">Programs</div>
                    <div className={`kpiValue ${(plannerState?.program_count ?? 0) > 0 ? "success" : "warn"}`}>{plannerState?.program_count ?? 0}</div>
                    <div className="kpiMeta">{(plannerState?.program_count ?? 0) > 0 ? "Ready" : "None loaded"}</div>
                  </div>
                  <div className="kpiCard">
                    <div className="kpiLabel">Transfer Rules</div>
                    <div className={`kpiValue ${(plannerState?.sbctc_mandate_count ?? 0) > 0 ? "success" : "warn"}`}>{plannerState?.sbctc_mandate_count ?? 0}</div>
                    <div className="kpiMeta">SBCTC mandates</div>
                  </div>
                  <div className="kpiCard">
                    <div className="kpiLabel">Regex Corpus</div>
                    <div className={`kpiValue ${(plannerState?.regex_corpus_record_count ?? 0) > 100 ? "success" : "warn"}`}>{plannerState?.regex_corpus_record_count ?? 0}</div>
                    <div className="kpiMeta">Indexed records</div>
                  </div>
                  <div className="kpiCard">
                    <div className="kpiLabel">Live Catalog</div>
                    <div className={`kpiValue ${(plannerState?.live_catalog_course_count ?? 0) > 0 ? "success" : "warn"}`}>{plannerState?.live_catalog_course_count ?? 0}</div>
                    <div className="kpiMeta">{liveCatalogFreshness}</div>
                  </div>
                </div>

                <div className="grid-2">
                  <div className="card">
                    <div className="card-title"><span className="card-title-icon">📂</span> Import Programs</div>
                    <div className="form-group">
                      <div className="form-label">Program PDF(s)</div>
                      <input type="file" accept=".pdf" multiple onChange={(e) => e.target.files && importProgramPdf(e.target.files)} />
                    </div>
                    <div className="form-group">
                      <div className="form-label">Program JSON</div>
                      <input type="file" accept=".json" onChange={(e) => e.target.files?.[0] && importProgramJson(e.target.files[0])} />
                    </div>
                    {programImportStatus && <div className="status-line">{programImportStatus}</div>}
                  </div>

                  <div className="card">
                    <div className="card-title"><span className="card-title-icon">🔁</span> Transfer Rules</div>
                    <div className="form-group">
                      <div className="form-label">Rules JSON</div>
                      <input type="file" accept=".json" onChange={(e) => e.target.files?.[0] && importRulesJson(e.target.files[0])} />
                    </div>
                    {rulesImportStatus && <div className="status-line">{rulesImportStatus}</div>}
                    <div className="status-line">Equivalencies: {plannerState?.transfer_equivalency_count ?? 0}  ·  SBCTC: {plannerState?.sbctc_mandate_count ?? 0}</div>
                  </div>

                  <div className="card">
                    <div className="card-title"><span className="card-title-icon">🌐</span> Live Quarterly Catalog (ctcLink)</div>
                    <div className="form-group">
                      <div className="form-label">Institution Code</div>
                      <input type="text" value={liveInstitutionCode} onChange={(e) => setLiveInstitutionCode(e.target.value)} />
                    </div>
                    <div className="form-group">
                      <div className="form-label">Class Search URL</div>
                      <input type="text" value={liveClassSearchUrl} onChange={(e) => setLiveClassSearchUrl(e.target.value)} />
                    </div>
                    <div className="grid-2" style={{ gap: "0.5rem" }}>
                      <div className="form-group">
                        <div className="form-label">Term Codes (optional)</div>
                        <input type="text" value={liveTermCodes} onChange={(e) => setLiveTermCodes(e.target.value)} placeholder="2263,2265" />
                      </div>
                      <div className="form-group">
                        <div className="form-label">Auto Term Count</div>
                        <input type="number" value={liveTermCount} onChange={(e) => setLiveTermCount(Number(e.target.value || 3))} />
                      </div>
                    </div>
                    <div className="form-group">
                      <div className="form-label">Advanced Params (JSON)</div>
                      <input type="text" value={liveSearchParamsJson} onChange={(e) => setLiveSearchParamsJson(e.target.value)} placeholder='{"KEYWORD":"math"}' />
                    </div>
                    <div className="btn-row">
                      <button className="btn btn-primary" disabled={busy} onClick={updateLiveCatalog}>Refresh Live Catalog</button>
                      <button className="btn btn-ghost" disabled={busy} onClick={() => refreshPlannerState()}>Refresh State</button>
                    </div>
                    {liveCatalogMessage && <div className="status-line" style={{ marginTop: "0.4rem" }}>{liveCatalogMessage}</div>}
                    {liveCatalogStatus && (
                      <div className="status-line">
                        {liveCatalogStatus.row_count ?? 0} rows  ·  {(liveCatalogStatus.term_codes || []).join(", ") || "—"}
                        {liveCatalogStatus.delta && (
                          <>  ·  Δ +{liveCatalogStatus.delta.added_count ?? 0} -{liveCatalogStatus.delta.removed_count ?? 0} ~{liveCatalogStatus.delta.changed_count ?? 0}</>
                        )}
                      </div>
                    )}
                  </div>

                  <div className="card">
                    <div className="card-title"><span className="card-title-icon">🔎</span> Regex Corpus &amp; Policy QA</div>
                    <div className="status-line">Indexed records: {plannerState?.regex_corpus_record_count ?? 0}</div>
                    <div className="btn-row" style={{ margin: "0.5rem 0" }}>
                      <button className="btn btn-primary" disabled={busy} onClick={reindexRegexCorpus}>Reindex Corpus</button>
                      <button className="btn" disabled={busy} onClick={runPolicyQA}>Run Policy QA</button>
                    </div>
                    {regexMessage && <div className="status-line">{regexMessage}</div>}
                    {policyQaMessage && <div className="status-line">{policyQaMessage}</div>}
                    {policyQa?.severity_counts && (
                      <div style={{ marginTop: "0.5rem", display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                        <span className="req-pill danger">High: {policyQa.severity_counts.high ?? 0}</span>
                        <span className="req-pill partial">Med: {policyQa.severity_counts.medium ?? 0}</span>
                        <span className="req-pill complete">Low: {policyQa.severity_counts.low ?? 0}</span>
                      </div>
                    )}
                    {(policyQa?.issues || []).slice(0, 6).map((issue, i) => (
                      <div key={i} style={{ fontSize: "0.78rem", color: "var(--muted)", borderTop: "1px solid var(--line)", padding: "0.3rem 0" }}>
                        <span style={{ color: issue.severity === "high" ? "var(--danger)" : issue.severity === "medium" ? "var(--warn)" : "var(--faint)", marginRight: "0.4rem" }}>
                          [{issue.severity}]
                        </span>
                        {issue.scope && <span style={{ color: "var(--faint)", marginRight: "0.4rem" }}>{issue.scope}</span>}
                        {issue.message}
                      </div>
                    ))}
                  </div>

                  <div className="card">
                    <div className="card-title"><span className="card-title-icon">🔭</span> Quick Catalog Text Search</div>
                    <div className="inline-row">
                      <input type="text" value={catalogQuery} onChange={(e) => setCatalogQuery(e.target.value)}
                        placeholder="ENGL&101, MATH 141, instructor…"
                        onKeyDown={(e) => e.key === "Enter" && legacyCatalogSearch()} />
                      <button className="btn" onClick={legacyCatalogSearch}>Search</button>
                    </div>
                    <div style={{ maxHeight: 200, overflowY: "auto", marginTop: "0.5rem" }}>
                      {offerings.slice(0, 30).map((o, i) => (
                        <div key={i} className="course-row" style={{ gridTemplateColumns: "6rem 1fr 4rem" }}
                          onClick={() => setSelectedOffering(o)}>
                          <span className="course-code">{o.course_code || "—"}</span>
                          <span className="course-title">{o.title || "—"}</span>
                          <span style={{ color: "var(--muted)", fontSize: "0.78rem" }}>{o.term || "—"}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

      </main>
    </div>
  );
}
