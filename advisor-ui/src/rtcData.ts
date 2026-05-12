// ─── RTC Static Program Data ──────────────────────────────────────────────────
// Renton Technical College — Career Programs, Courses, and Degree Maps
// Source: RTC Academic Catalog (static reference for demo / freeform mode)
// Live backend data takes precedence when available.

export type RtcCourse = {
  code: string;           // e.g. "CIS 110"
  title: string;
  credits: number;
  prereqs?: string[];     // course codes required before this
  timeOptions?: ("day" | "evening" | "online")[];
  itemNumber?: string;    // ctcLink item number placeholder
  isCore?: boolean;
  isTransfer?: boolean;
};

export type QuarterSlot = {
  year: number;
  season: "Fall" | "Winter" | "Spring" | "Summer";
  monthRange: string;
  courses: string[];      // course codes
  totalCredits?: number;
};

export type PrereqGroup = {
  type: string;           // "Math", "English", "General Education", etc.
  description: string;
  minCredits: number;
  options: string[];      // course codes satisfying this group
};

export type RtcProgram = {
  id: string;
  name: string;
  award: "AAS" | "AA" | "AS" | "AAS-T" | "Certificate" | "Short Certificate" | "BAS" | "AAT";
  categoryId: string;
  totalCredits: number;
  years: number;
  description: string;
  quarterPlan: QuarterSlot[];
  prereqGroups?: PrereqGroup[];
  courses: RtcCourse[];
};

export type RtcCareerCategory = {
  id: string;
  name: string;
  icon: string;
  description: string;
  programs: RtcProgram[];
};

// ─── Shared / General Education Courses ───────────────────────────────────────

const GENED_COURSES: RtcCourse[] = [
  { code: "ENGL 101", title: "English Composition I", credits: 5, timeOptions: ["day", "evening", "online"] },
  { code: "ENGL 102", title: "English Composition II", credits: 5, prereqs: ["ENGL 101"], timeOptions: ["day", "evening", "online"] },
  { code: "ENGL&101", title: "English Composition (transfer)", credits: 5, timeOptions: ["day", "evening", "online"], isTransfer: true },
  { code: "MATH 107", title: "Math in Society", credits: 5, timeOptions: ["day", "evening", "online"] },
  { code: "MATH 141", title: "Precalculus I", credits: 5, prereqs: ["MATH 107"], timeOptions: ["day", "evening"] },
  { code: "MATH 151", title: "Calculus I", credits: 5, prereqs: ["MATH 141"], timeOptions: ["day"] },
  { code: "MATH&107", title: "Math in Society (transfer)", credits: 5, timeOptions: ["day", "online"], isTransfer: true },
  { code: "COMM 101", title: "Introduction to Communication", credits: 5, timeOptions: ["day", "evening", "online"] },
  { code: "COMM 102", title: "Interpersonal Communication", credits: 3, timeOptions: ["day", "evening", "online"] },
  { code: "PSYC 100", title: "Introduction to Psychology", credits: 5, timeOptions: ["day", "evening", "online"] },
  { code: "SOCY 101", title: "Introduction to Sociology", credits: 5, timeOptions: ["day", "online"] },
  { code: "POLS 202", title: "American Government", credits: 5, timeOptions: ["day", "evening", "online"] },
  { code: "HIST 111", title: "U.S. History I", credits: 5, timeOptions: ["day", "online"] },
  { code: "BIOL 101", title: "Introduction to Biology", credits: 5, timeOptions: ["day"] },
  { code: "CHEM 110", title: "Introduction to Chemistry", credits: 5, timeOptions: ["day"] },
];

// ─── CATEGORY 1: Information Technology ───────────────────────────────────────

const IT_COURSES: RtcCourse[] = [
  { code: "CIS 110", title: "Introduction to Computer Information Systems", credits: 5, isCore: true, timeOptions: ["day", "evening", "online"] },
  { code: "CIS 111", title: "PC Hardware & Operating Systems", credits: 5, prereqs: ["CIS 110"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "CIS 112", title: "Networking Fundamentals", credits: 5, prereqs: ["CIS 110"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "CIS 120", title: "Introduction to Programming", credits: 5, prereqs: ["CIS 110"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "CIS 130", title: "Database Fundamentals", credits: 5, prereqs: ["CIS 110"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "CIS 210", title: "Systems Analysis & Design", credits: 5, prereqs: ["CIS 120", "CIS 130"], isCore: true, timeOptions: ["day"] },
  { code: "CIS 211", title: "Object-Oriented Programming", credits: 5, prereqs: ["CIS 120"], isCore: true, timeOptions: ["day"] },
  { code: "CIS 212", title: "Web Application Development", credits: 5, prereqs: ["CIS 120"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "CIS 220", title: "Advanced Database", credits: 5, prereqs: ["CIS 130"], isCore: true, timeOptions: ["day"] },
  { code: "CIS 230", title: "Cloud Computing Fundamentals", credits: 5, prereqs: ["CIS 112"], isCore: true, timeOptions: ["day", "online"] },
  { code: "CIS 240", title: "IT Project Management", credits: 3, prereqs: ["CIS 210"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "CIS 250", title: "Capstone: Systems Integration", credits: 5, prereqs: ["CIS 210", "CIS 211"], isCore: true, timeOptions: ["day"] },
  // Cybersecurity specific
  { code: "CSEC 101", title: "Cybersecurity Fundamentals", credits: 5, prereqs: ["CIS 110"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "CSEC 110", title: "Network Security Essentials", credits: 5, prereqs: ["CIS 112", "CSEC 101"], isCore: true, timeOptions: ["day"] },
  { code: "CSEC 120", title: "Ethical Hacking & Penetration Testing", credits: 5, prereqs: ["CSEC 110"], isCore: true, timeOptions: ["day"] },
  { code: "CSEC 130", title: "Digital Forensics", credits: 5, prereqs: ["CSEC 101"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "CSEC 200", title: "Security Operations Center (SOC)", credits: 5, prereqs: ["CSEC 110", "CSEC 130"], isCore: true, timeOptions: ["day"] },
  { code: "CSEC 210", title: "Cloud Security", credits: 5, prereqs: ["CSEC 110", "CIS 230"], isCore: true, timeOptions: ["day"] },
  { code: "CSEC 220", title: "Compliance & Risk Management", credits: 3, prereqs: ["CSEC 200"], isCore: true, timeOptions: ["day", "online"] },
  { code: "CSEC 250", title: "Cybersecurity Capstone", credits: 5, prereqs: ["CSEC 200", "CSEC 210"], isCore: true, timeOptions: ["day"] },
  // Web Dev specific
  { code: "WEBD 101", title: "HTML & CSS Fundamentals", credits: 5, isCore: true, timeOptions: ["day", "evening", "online"] },
  { code: "WEBD 110", title: "JavaScript Programming", credits: 5, prereqs: ["WEBD 101"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "WEBD 120", title: "Responsive Web Design", credits: 5, prereqs: ["WEBD 101"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "WEBD 210", title: "Front-End Frameworks (React)", credits: 5, prereqs: ["WEBD 110"], isCore: true, timeOptions: ["day"] },
  { code: "WEBD 220", title: "Back-End Web Development", credits: 5, prereqs: ["WEBD 110", "CIS 130"], isCore: true, timeOptions: ["day"] },
  { code: "WEBD 250", title: "Web Development Capstone", credits: 5, prereqs: ["WEBD 210", "WEBD 220"], isCore: true, timeOptions: ["day"] },
  // Network
  { code: "NETW 110", title: "Network Infrastructure", credits: 5, prereqs: ["CIS 112"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "NETW 120", title: "Routing & Switching", credits: 5, prereqs: ["NETW 110"], isCore: true, timeOptions: ["day"] },
  { code: "NETW 130", title: "Wireless Networking", credits: 5, prereqs: ["NETW 110"], isCore: true, timeOptions: ["day"] },
  { code: "NETW 200", title: "Network Administration", credits: 5, prereqs: ["NETW 120"], isCore: true, timeOptions: ["day"] },
];

// ─── CATEGORY 2: Business & Management ────────────────────────────────────────

const BUS_COURSES: RtcCourse[] = [
  { code: "BUSA 100", title: "Introduction to Business", credits: 3, isCore: true, timeOptions: ["day", "evening", "online"] },
  { code: "BUSA 101", title: "Business Communications", credits: 3, isCore: true, timeOptions: ["day", "evening", "online"] },
  { code: "BUSA 110", title: "Principles of Management", credits: 5, prereqs: ["BUSA 100"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "BUSA 115", title: "Business Law", credits: 5, isCore: true, timeOptions: ["day", "evening", "online"] },
  { code: "BUSA 120", title: "Principles of Marketing", credits: 5, prereqs: ["BUSA 100"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "BUSA 200", title: "Organizational Behavior", credits: 3, prereqs: ["BUSA 110"], isCore: true, timeOptions: ["day", "online"] },
  { code: "BUSA 210", title: "Human Resources Management", credits: 5, prereqs: ["BUSA 110"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "BUSA 220", title: "Entrepreneurship", credits: 3, prereqs: ["BUSA 110"], isCore: true, timeOptions: ["day", "online"] },
  // Accounting
  { code: "ACCT 101", title: "Accounting Fundamentals I", credits: 5, isCore: true, timeOptions: ["day", "evening", "online"] },
  { code: "ACCT 102", title: "Accounting Fundamentals II", credits: 5, prereqs: ["ACCT 101"], isCore: true, timeOptions: ["day", "evening", "online"] },
  { code: "ACCT 111", title: "QuickBooks Accounting Software", credits: 3, prereqs: ["ACCT 101"], isCore: true, timeOptions: ["day", "evening", "online"] },
  { code: "ACCT 200", title: "Managerial Accounting", credits: 5, prereqs: ["ACCT 102"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "ACCT 210", title: "Tax Accounting", credits: 5, prereqs: ["ACCT 102"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "ACCT 220", title: "Payroll Accounting", credits: 3, prereqs: ["ACCT 101"], isCore: true, timeOptions: ["day", "evening", "online"] },
  { code: "ACCT 230", title: "Accounting Capstone", credits: 5, prereqs: ["ACCT 200", "ACCT 210"], isCore: true, timeOptions: ["day"] },
  // Office Admin
  { code: "OFAD 101", title: "Office Applications I (Word/Excel)", credits: 5, isCore: true, timeOptions: ["day", "evening", "online"] },
  { code: "OFAD 102", title: "Office Applications II (Access/PowerPoint)", credits: 5, prereqs: ["OFAD 101"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "OFAD 110", title: "Records Management", credits: 3, isCore: true, timeOptions: ["day", "evening", "online"] },
  { code: "OFAD 120", title: "Business Writing", credits: 3, isCore: true, timeOptions: ["day", "online"] },
  { code: "OFAD 200", title: "Administrative Procedures", credits: 5, prereqs: ["OFAD 101", "OFAD 110"], isCore: true, timeOptions: ["day"] },
];

// ─── CATEGORY 3: Healthcare ────────────────────────────────────────────────────

const HEALTH_COURSES: RtcCourse[] = [
  { code: "MA 101", title: "Medical Terminology", credits: 5, isCore: true, timeOptions: ["day", "evening", "online"] },
  { code: "MA 110", title: "Medical Assistant Fundamentals", credits: 5, prereqs: ["MA 101"], isCore: true, timeOptions: ["day"] },
  { code: "MA 120", title: "Clinical Procedures I", credits: 5, prereqs: ["MA 110"], isCore: true, timeOptions: ["day"] },
  { code: "MA 130", title: "Clinical Procedures II", credits: 5, prereqs: ["MA 120"], isCore: true, timeOptions: ["day"] },
  { code: "MA 140", title: "Pharmacology for Medical Assistants", credits: 3, prereqs: ["MA 110"], isCore: true, timeOptions: ["day"] },
  { code: "MA 150", title: "Administrative Medical Procedures", credits: 5, prereqs: ["MA 110"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "MA 200", title: "EKG & Phlebotomy", credits: 5, prereqs: ["MA 120"], isCore: true, timeOptions: ["day"] },
  { code: "MA 210", title: "Medical Office Management", credits: 3, prereqs: ["MA 150"], isCore: true, timeOptions: ["day"] },
  { code: "MA 250", title: "Medical Assistant Practicum", credits: 5, prereqs: ["MA 130", "MA 200"], isCore: true, timeOptions: ["day"] },
  // Dental
  { code: "DA 100", title: "Dental Assisting Fundamentals", credits: 5, isCore: true, timeOptions: ["day"] },
  { code: "DA 110", title: "Dental Sciences", credits: 5, prereqs: ["DA 100"], isCore: true, timeOptions: ["day"] },
  { code: "DA 120", title: "Chairside Dental Assisting", credits: 5, prereqs: ["DA 110"], isCore: true, timeOptions: ["day"] },
  { code: "DA 130", title: "Dental Radiology", credits: 3, prereqs: ["DA 110"], isCore: true, timeOptions: ["day"] },
  { code: "DA 140", title: "Dental Materials & Lab", credits: 3, prereqs: ["DA 110"], isCore: true, timeOptions: ["day"] },
  { code: "DA 200", title: "Expanded Function Dental Assisting", credits: 5, prereqs: ["DA 120", "DA 130"], isCore: true, timeOptions: ["day"] },
  { code: "DA 250", title: "Dental Assisting Externship", credits: 5, prereqs: ["DA 200"], isCore: true, timeOptions: ["day"] },
  // Nursing
  { code: "NURS 100", title: "Foundations of Nursing", credits: 8, isCore: true, timeOptions: ["day"] },
  { code: "NURS 110", title: "Medical-Surgical Nursing I", credits: 8, prereqs: ["NURS 100"], isCore: true, timeOptions: ["day"] },
  { code: "NURS 120", title: "Pharmacology for Nurses", credits: 5, prereqs: ["NURS 100"], isCore: true, timeOptions: ["day", "online"] },
  { code: "NURS 130", title: "Mental Health Nursing", credits: 5, prereqs: ["NURS 110"], isCore: true, timeOptions: ["day"] },
  { code: "NURS 140", title: "Maternal-Newborn Nursing", credits: 5, prereqs: ["NURS 110"], isCore: true, timeOptions: ["day"] },
  { code: "NURS 200", title: "Medical-Surgical Nursing II", credits: 8, prereqs: ["NURS 110"], isCore: true, timeOptions: ["day"] },
  { code: "NURS 210", title: "Pediatric Nursing", credits: 5, prereqs: ["NURS 200"], isCore: true, timeOptions: ["day"] },
  { code: "NURS 220", title: "Community Health Nursing", credits: 5, prereqs: ["NURS 200"], isCore: true, timeOptions: ["day"] },
  { code: "NURS 250", title: "Nursing Capstone & NCLEX Prep", credits: 5, prereqs: ["NURS 210", "NURS 220"], isCore: true, timeOptions: ["day"] },
  // Pharmacy
  { code: "PHRM 100", title: "Pharmacy Technician Fundamentals", credits: 5, isCore: true, timeOptions: ["day", "evening"] },
  { code: "PHRM 110", title: "Pharmacology I", credits: 5, prereqs: ["PHRM 100"], isCore: true, timeOptions: ["day"] },
  { code: "PHRM 120", title: "Pharmacy Law & Ethics", credits: 3, prereqs: ["PHRM 100"], isCore: true, timeOptions: ["day", "online"] },
  { code: "PHRM 130", title: "Sterile Compounding", credits: 5, prereqs: ["PHRM 110"], isCore: true, timeOptions: ["day"] },
  { code: "PHRM 200", title: "Pharmacy Technician Practicum", credits: 5, prereqs: ["PHRM 130"], isCore: true, timeOptions: ["day"] },
];

// ─── CATEGORY 4: Applied Technology ───────────────────────────────────────────

const TECH_COURSES: RtcCourse[] = [
  // Electrical
  { code: "ELET 101", title: "Electrical Theory I", credits: 5, isCore: true, timeOptions: ["day", "evening"] },
  { code: "ELET 102", title: "Electrical Theory II", credits: 5, prereqs: ["ELET 101"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "ELET 110", title: "NEC Code & Wiring Methods I", credits: 5, prereqs: ["ELET 101"], isCore: true, timeOptions: ["day"] },
  { code: "ELET 120", title: "NEC Code & Wiring Methods II", credits: 5, prereqs: ["ELET 110"], isCore: true, timeOptions: ["day"] },
  { code: "ELET 130", title: "Motor Controls", credits: 5, prereqs: ["ELET 102"], isCore: true, timeOptions: ["day"] },
  { code: "ELET 140", title: "PLC Programming", credits: 5, prereqs: ["ELET 130"], isCore: true, timeOptions: ["day"] },
  { code: "ELET 200", title: "Commercial Wiring", credits: 5, prereqs: ["ELET 120"], isCore: true, timeOptions: ["day"] },
  { code: "ELET 210", title: "Industrial Electrical Systems", credits: 5, prereqs: ["ELET 200"], isCore: true, timeOptions: ["day"] },
  { code: "ELET 250", title: "Electrical Capstone", credits: 5, prereqs: ["ELET 210", "ELET 140"], isCore: true, timeOptions: ["day"] },
  // Welding
  { code: "WELD 101", title: "Welding Safety & Orientation", credits: 2, isCore: true, timeOptions: ["day", "evening"] },
  { code: "WELD 110", title: "SMAW (Stick Welding)", credits: 5, prereqs: ["WELD 101"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "WELD 120", title: "GMAW (MIG Welding)", credits: 5, prereqs: ["WELD 101"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "WELD 130", title: "GTAW (TIG Welding)", credits: 5, prereqs: ["WELD 110"], isCore: true, timeOptions: ["day"] },
  { code: "WELD 140", title: "Blueprint Reading for Welders", credits: 3, isCore: true, timeOptions: ["day", "evening"] },
  { code: "WELD 200", title: "Welding Certification Prep", credits: 5, prereqs: ["WELD 130"], isCore: true, timeOptions: ["day"] },
  { code: "WELD 210", title: "Pipe Welding", credits: 5, prereqs: ["WELD 200"], isCore: true, timeOptions: ["day"] },
  { code: "WELD 250", title: "Welding Capstone & Portfolio", credits: 3, prereqs: ["WELD 200"], isCore: true, timeOptions: ["day"] },
  // HVAC
  { code: "HVAC 100", title: "HVAC/R Fundamentals", credits: 5, isCore: true, timeOptions: ["day"] },
  { code: "HVAC 110", title: "Refrigeration Theory & Systems", credits: 5, prereqs: ["HVAC 100"], isCore: true, timeOptions: ["day"] },
  { code: "HVAC 120", title: "Heating Systems", credits: 5, prereqs: ["HVAC 100"], isCore: true, timeOptions: ["day"] },
  { code: "HVAC 130", title: "Air Distribution & Ventilation", credits: 5, prereqs: ["HVAC 110"], isCore: true, timeOptions: ["day"] },
  { code: "HVAC 140", title: "EPA 608 Certification Prep", credits: 3, prereqs: ["HVAC 110"], isCore: true, timeOptions: ["day"] },
  { code: "HVAC 200", title: "Commercial HVAC Systems", credits: 5, prereqs: ["HVAC 130"], isCore: true, timeOptions: ["day"] },
  { code: "HVAC 210", title: "HVAC Controls & Automation", credits: 5, prereqs: ["HVAC 200"], isCore: true, timeOptions: ["day"] },
  { code: "HVAC 250", title: "HVAC Capstone", credits: 3, prereqs: ["HVAC 200"], isCore: true, timeOptions: ["day"] },
];

// ─── CATEGORY 5: Automotive Technology ────────────────────────────────────────

const AUTO_COURSES: RtcCourse[] = [
  { code: "AUTO 101", title: "Automotive Fundamentals", credits: 5, isCore: true, timeOptions: ["day", "evening"] },
  { code: "AUTO 110", title: "Engine Performance I", credits: 5, prereqs: ["AUTO 101"], isCore: true, timeOptions: ["day"] },
  { code: "AUTO 120", title: "Brakes & Suspension", credits: 5, prereqs: ["AUTO 101"], isCore: true, timeOptions: ["day", "evening"] },
  { code: "AUTO 130", title: "Electrical Systems", credits: 5, prereqs: ["AUTO 101"], isCore: true, timeOptions: ["day"] },
  { code: "AUTO 140", title: "Automotive HVAC", credits: 3, prereqs: ["AUTO 101"], isCore: true, timeOptions: ["day"] },
  { code: "AUTO 150", title: "Automatic Transmissions", credits: 5, prereqs: ["AUTO 110"], isCore: true, timeOptions: ["day"] },
  { code: "AUTO 200", title: "Engine Performance II", credits: 5, prereqs: ["AUTO 110", "AUTO 130"], isCore: true, timeOptions: ["day"] },
  { code: "AUTO 210", title: "Advanced Diagnostics", credits: 5, prereqs: ["AUTO 200"], isCore: true, timeOptions: ["day"] },
  { code: "AUTO 220", title: "Hybrid & Electric Vehicles", credits: 5, prereqs: ["AUTO 130"], isCore: true, timeOptions: ["day"] },
  { code: "AUTO 250", title: "Automotive Capstone", credits: 5, prereqs: ["AUTO 200", "AUTO 210"], isCore: true, timeOptions: ["day"] },
];

// ─── CATEGORY 6: Culinary Arts ─────────────────────────────────────────────────

const CULN_COURSES: RtcCourse[] = [
  { code: "CULN 101", title: "Introduction to Culinary Arts", credits: 5, isCore: true, timeOptions: ["day", "evening"] },
  { code: "CULN 110", title: "Culinary Techniques I", credits: 5, prereqs: ["CULN 101"], isCore: true, timeOptions: ["day"] },
  { code: "CULN 120", title: "Culinary Techniques II", credits: 5, prereqs: ["CULN 110"], isCore: true, timeOptions: ["day"] },
  { code: "CULN 130", title: "Nutrition & Menu Planning", credits: 3, prereqs: ["CULN 101"], isCore: true, timeOptions: ["day", "online"] },
  { code: "CULN 140", title: "Food Safety & Sanitation (ServSafe)", credits: 3, isCore: true, timeOptions: ["day", "evening", "online"] },
  { code: "CULN 150", title: "Baking & Pastry Fundamentals", credits: 5, prereqs: ["CULN 101"], isCore: true, timeOptions: ["day"] },
  { code: "CULN 200", title: "Global Cuisines", credits: 5, prereqs: ["CULN 120"], isCore: true, timeOptions: ["day"] },
  { code: "CULN 210", title: "Restaurant Operations & Management", credits: 5, prereqs: ["CULN 120"], isCore: true, timeOptions: ["day"] },
  { code: "CULN 250", title: "Culinary Capstone & Practicum", credits: 5, prereqs: ["CULN 200", "CULN 210"], isCore: true, timeOptions: ["day"] },
  // Baking specific
  { code: "BAKE 101", title: "Baking Fundamentals", credits: 5, isCore: true, timeOptions: ["day"] },
  { code: "BAKE 110", title: "Breads & Yeast Products", credits: 5, prereqs: ["BAKE 101"], isCore: true, timeOptions: ["day"] },
  { code: "BAKE 120", title: "Pastry & Desserts", credits: 5, prereqs: ["BAKE 101"], isCore: true, timeOptions: ["day"] },
  { code: "BAKE 130", title: "Cake Decoration & Design", credits: 3, prereqs: ["BAKE 120"], isCore: true, timeOptions: ["day"] },
  { code: "BAKE 200", title: "Advanced Pastry Arts", credits: 5, prereqs: ["BAKE 120"], isCore: true, timeOptions: ["day"] },
  { code: "BAKE 250", title: "Baking Capstone", credits: 3, prereqs: ["BAKE 200"], isCore: true, timeOptions: ["day"] },
];

// ─── CATEGORY 7: Construction & Trades ────────────────────────────────────────

const CONST_COURSES: RtcCourse[] = [
  { code: "CARP 100", title: "Construction Fundamentals", credits: 5, isCore: true, timeOptions: ["day"] },
  { code: "CARP 110", title: "Framing & Structural Systems", credits: 5, prereqs: ["CARP 100"], isCore: true, timeOptions: ["day"] },
  { code: "CARP 120", title: "Blueprint Reading for Construction", credits: 3, isCore: true, timeOptions: ["day", "evening"] },
  { code: "CARP 130", title: "Exterior Finish", credits: 5, prereqs: ["CARP 110"], isCore: true, timeOptions: ["day"] },
  { code: "CARP 140", title: "Interior Finish", credits: 5, prereqs: ["CARP 130"], isCore: true, timeOptions: ["day"] },
  { code: "CARP 150", title: "Concrete & Masonry", credits: 5, prereqs: ["CARP 100"], isCore: true, timeOptions: ["day"] },
  { code: "CARP 200", title: "Advanced Construction Techniques", credits: 5, prereqs: ["CARP 140"], isCore: true, timeOptions: ["day"] },
  { code: "CARP 210", title: "Construction Project Management", credits: 3, prereqs: ["CARP 200"], isCore: true, timeOptions: ["day"] },
  { code: "CARP 250", title: "Construction Capstone", credits: 5, prereqs: ["CARP 200"], isCore: true, timeOptions: ["day"] },
];

// ─── CATEGORY 8: Transfer Education ───────────────────────────────────────────

const TRANSFER_COURSES: RtcCourse[] = [
  { code: "ENGL&101", title: "English Composition I", credits: 5, isCore: true, isTransfer: true, timeOptions: ["day", "evening", "online"] },
  { code: "ENGL&102", title: "English Composition II", credits: 5, prereqs: ["ENGL&101"], isCore: true, isTransfer: true, timeOptions: ["day", "evening", "online"] },
  { code: "MATH&141", title: "Precalculus I", credits: 5, isCore: true, isTransfer: true, timeOptions: ["day", "evening"] },
  { code: "MATH&142", title: "Precalculus II", credits: 5, prereqs: ["MATH&141"], isCore: true, isTransfer: true, timeOptions: ["day"] },
  { code: "MATH&151", title: "Calculus I", credits: 5, prereqs: ["MATH&142"], isCore: true, isTransfer: true, timeOptions: ["day"] },
  { code: "MATH&152", title: "Calculus II", credits: 5, prereqs: ["MATH&151"], isCore: true, isTransfer: true, timeOptions: ["day"] },
  { code: "CHEM&121", title: "General Chemistry I", credits: 5, prereqs: ["MATH&141"], isCore: true, isTransfer: true, timeOptions: ["day"] },
  { code: "BIOL&211", title: "Majors Biology I (Cell/Molecular)", credits: 5, isCore: true, isTransfer: true, timeOptions: ["day"] },
  { code: "PSYC&100", title: "General Psychology", credits: 5, isCore: true, isTransfer: true, timeOptions: ["day", "evening", "online"] },
  { code: "SOCY&101", title: "Introduction to Sociology", credits: 5, isCore: true, isTransfer: true, timeOptions: ["day", "online"] },
  { code: "POLS&202", title: "American Government", credits: 5, isCore: true, isTransfer: true, timeOptions: ["day", "online"] },
  { code: "HIST&111", title: "U.S. History I", credits: 5, isCore: true, isTransfer: true, timeOptions: ["day", "online"] },
  { code: "HIST&112", title: "U.S. History II", credits: 5, prereqs: ["HIST&111"], isCore: true, isTransfer: true, timeOptions: ["day", "online"] },
  { code: "ECON&201", title: "Microeconomics", credits: 5, isCore: true, isTransfer: true, timeOptions: ["day", "online"] },
  { code: "ECON&202", title: "Macroeconomics", credits: 5, isCore: true, isTransfer: true, timeOptions: ["day", "online"] },
  { code: "COMM&101", title: "Introduction to Communication", credits: 5, isCore: true, isTransfer: true, timeOptions: ["day", "evening", "online"] },
  { code: "PHIL&101", title: "Introduction to Philosophy", credits: 5, isCore: true, isTransfer: true, timeOptions: ["day", "online"] },
  { code: "ART&101", title: "Art History I", credits: 5, isCore: true, isTransfer: true, timeOptions: ["day", "online"] },
  { code: "MUSC&141", title: "Music Appreciation", credits: 5, isCore: true, isTransfer: true, timeOptions: ["day", "online"] },
  { code: "PE&101", title: "Physical Education / Wellness", credits: 2, isCore: true, isTransfer: true, timeOptions: ["day"] },
];

// ─── Program Definitions ───────────────────────────────────────────────────────

export const RTC_CAREER_CATEGORIES: RtcCareerCategory[] = [
  // ── 1. Information Technology ──────────────────────────────────────────────
  {
    id: "it",
    name: "Information Technology",
    icon: "💻",
    description: "Computer science, cybersecurity, networking, and web development programs",
    programs: [
      {
        id: "cis-aas",
        name: "Computer Information Systems",
        award: "AAS",
        categoryId: "it",
        totalCredits: 90,
        years: 2,
        description: "Prepare for careers in IT support, software development, and systems administration",
        courses: [...IT_COURSES, ...GENED_COURSES.slice(0, 4)],
        prereqGroups: [
          { type: "English", description: "College-level writing requirement", minCredits: 5, options: ["ENGL 101", "ENGL&101"] },
          { type: "Math", description: "Quantitative reasoning requirement", minCredits: 5, options: ["MATH 107", "MATH&107", "MATH 141"] },
          { type: "Communication", description: "Oral communication requirement", minCredits: 3, options: ["COMM 101", "COMM 102"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["CIS 110", "ENGL 101", "MATH 107"], totalCredits: 15 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["CIS 111", "CIS 112", "COMM 102"], totalCredits: 13 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["CIS 120", "CIS 130", "PSYC 100"], totalCredits: 15 },
          { year: 2, season: "Fall",   monthRange: "Sep–Nov", courses: ["CIS 210", "CIS 211", "CIS 230"], totalCredits: 15 },
          { year: 2, season: "Winter", monthRange: "Jan–Mar", courses: ["CIS 212", "CIS 220", "CIS 240"], totalCredits: 13 },
          { year: 2, season: "Spring", monthRange: "Apr–Jun", courses: ["CIS 250"], totalCredits: 5 },
        ],
      },
      {
        id: "csec-aas",
        name: "Cybersecurity",
        award: "AAS",
        categoryId: "it",
        totalCredits: 92,
        years: 2,
        description: "Hands-on cybersecurity training for network defense, ethical hacking, and digital forensics",
        courses: [...IT_COURSES, ...GENED_COURSES.slice(0, 3)],
        prereqGroups: [
          { type: "English", description: "College-level writing requirement", minCredits: 5, options: ["ENGL 101", "ENGL&101"] },
          { type: "Math", description: "Quantitative reasoning — algebra or higher", minCredits: 5, options: ["MATH 107", "MATH 141", "MATH&141"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["CIS 110", "CIS 112", "ENGL 101"], totalCredits: 15 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["CIS 111", "CSEC 101", "MATH 107"], totalCredits: 15 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["CSEC 110", "CSEC 130", "COMM 101"], totalCredits: 15 },
          { year: 2, season: "Fall",   monthRange: "Sep–Nov", courses: ["CSEC 120", "CIS 230", "CSEC 200"], totalCredits: 15 },
          { year: 2, season: "Winter", monthRange: "Jan–Mar", courses: ["CSEC 210", "CSEC 220"], totalCredits: 8 },
          { year: 2, season: "Spring", monthRange: "Apr–Jun", courses: ["CSEC 250"], totalCredits: 5 },
        ],
      },
      {
        id: "csec-cert",
        name: "Cybersecurity",
        award: "Certificate",
        categoryId: "it",
        totalCredits: 45,
        years: 1,
        description: "Accelerated cybersecurity fundamentals and network defense certification pathway",
        courses: IT_COURSES.filter(c => c.code.startsWith("CIS 1") || c.code.startsWith("CSEC 1")),
        prereqGroups: [
          { type: "English", description: "Reading/writing proficiency", minCredits: 5, options: ["ENGL 101"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["CIS 110", "CIS 112", "CSEC 101"], totalCredits: 15 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["CIS 111", "CSEC 110"], totalCredits: 10 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["CSEC 120", "CSEC 130"], totalCredits: 10 },
        ],
      },
      {
        id: "webd-cert",
        name: "Web Development",
        award: "Certificate",
        categoryId: "it",
        totalCredits: 50,
        years: 1,
        description: "Modern front-end and back-end web development for employment-ready skills",
        courses: [...IT_COURSES.filter(c => c.code.startsWith("WEBD") || c.code === "CIS 110" || c.code === "CIS 130")],
        prereqGroups: [
          { type: "English", description: "Written communication proficiency", minCredits: 5, options: ["ENGL 101"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["CIS 110", "WEBD 101"], totalCredits: 10 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["WEBD 110", "WEBD 120", "CIS 130"], totalCredits: 15 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["WEBD 210", "WEBD 220", "WEBD 250"], totalCredits: 15 },
        ],
      },
    ],
  },

  // ── 2. Business & Management ───────────────────────────────────────────────
  {
    id: "business",
    name: "Business & Management",
    icon: "📊",
    description: "Business administration, accounting, marketing, and office administration programs",
    programs: [
      {
        id: "busa-aas",
        name: "Business Administration",
        award: "AAS",
        categoryId: "business",
        totalCredits: 90,
        years: 2,
        description: "Prepare for management and administrative roles in business, government, and non-profit organizations",
        courses: [...BUS_COURSES, ...GENED_COURSES.slice(0, 5)],
        prereqGroups: [
          { type: "English", description: "College-level writing requirement", minCredits: 5, options: ["ENGL 101", "ENGL&101"] },
          { type: "Math", description: "Business math or higher", minCredits: 5, options: ["MATH 107", "MATH&107"] },
          { type: "Social Science", description: "Human behavior/social context", minCredits: 5, options: ["PSYC 100", "SOCY 101"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["BUSA 100", "ACCT 101", "ENGL 101"], totalCredits: 13 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["BUSA 101", "BUSA 110", "ACCT 102"], totalCredits: 11 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["BUSA 115", "BUSA 120", "MATH 107"], totalCredits: 15 },
          { year: 2, season: "Fall",   monthRange: "Sep–Nov", courses: ["BUSA 200", "BUSA 210", "OFAD 101"], totalCredits: 13 },
          { year: 2, season: "Winter", monthRange: "Jan–Mar", courses: ["BUSA 220", "ACCT 200", "COMM 101"], totalCredits: 13 },
          { year: 2, season: "Spring", monthRange: "Apr–Jun", courses: ["PSYC 100"], totalCredits: 5 },
        ],
      },
      {
        id: "acct-aas",
        name: "Accounting",
        award: "AAS",
        categoryId: "business",
        totalCredits: 90,
        years: 2,
        description: "Develop skills in bookkeeping, financial accounting, tax preparation, and managerial accounting",
        courses: [...BUS_COURSES, ...GENED_COURSES.slice(0, 3)],
        prereqGroups: [
          { type: "English", description: "Written communication requirement", minCredits: 5, options: ["ENGL 101", "ENGL&101"] },
          { type: "Math", description: "Math in society or higher", minCredits: 5, options: ["MATH 107", "MATH&107", "MATH 141"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["ACCT 101", "BUSA 100", "ENGL 101"], totalCredits: 13 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["ACCT 102", "BUSA 101", "MATH 107"], totalCredits: 13 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["ACCT 111", "BUSA 115", "OFAD 101"], totalCredits: 13 },
          { year: 2, season: "Fall",   monthRange: "Sep–Nov", courses: ["ACCT 200", "ACCT 220", "OFAD 102"], totalCredits: 13 },
          { year: 2, season: "Winter", monthRange: "Jan–Mar", courses: ["ACCT 210", "BUSA 110"], totalCredits: 10 },
          { year: 2, season: "Spring", monthRange: "Apr–Jun", courses: ["ACCT 230"], totalCredits: 5 },
        ],
      },
      {
        id: "acct-cert",
        name: "Accounting",
        award: "Certificate",
        categoryId: "business",
        totalCredits: 42,
        years: 1,
        description: "Core bookkeeping and accounting skills for immediate employment",
        courses: BUS_COURSES.filter(c => c.code.startsWith("ACCT")),
        prereqGroups: [
          { type: "Math", description: "Basic math proficiency", minCredits: 5, options: ["MATH 107"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["ACCT 101", "BUSA 100", "OFAD 101"], totalCredits: 13 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["ACCT 102", "ACCT 111", "BUSA 101"], totalCredits: 11 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["ACCT 220", "BUSA 115"], totalCredits: 8 },
        ],
      },
    ],
  },

  // ── 3. Healthcare ──────────────────────────────────────────────────────────
  {
    id: "healthcare",
    name: "Healthcare",
    icon: "🏥",
    description: "Medical assistant, dental assisting, nursing, and healthcare information programs",
    programs: [
      {
        id: "ma-aas",
        name: "Medical Assistant",
        award: "AAS",
        categoryId: "healthcare",
        totalCredits: 90,
        years: 2,
        description: "Prepare for clinical and administrative medical assisting roles in physician offices, clinics, and hospitals",
        courses: [...HEALTH_COURSES.filter(c => c.code.startsWith("MA")), ...GENED_COURSES.slice(0, 4)],
        prereqGroups: [
          { type: "English", description: "Written communication for healthcare", minCredits: 5, options: ["ENGL 101", "ENGL&101"] },
          { type: "Biology", description: "Life sciences foundation", minCredits: 5, options: ["BIOL 101"] },
          { type: "Math", description: "Dosage calculation proficiency", minCredits: 5, options: ["MATH 107"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["MA 101", "ENGL 101", "BIOL 101"], totalCredits: 15 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["MA 110", "MA 140", "MATH 107"], totalCredits: 13 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["MA 120", "MA 150", "COMM 101"], totalCredits: 15 },
          { year: 2, season: "Fall",   monthRange: "Sep–Nov", courses: ["MA 130", "MA 200"], totalCredits: 10 },
          { year: 2, season: "Winter", monthRange: "Jan–Mar", courses: ["MA 210", "PSYC 100"], totalCredits: 8 },
          { year: 2, season: "Spring", monthRange: "Apr–Jun", courses: ["MA 250"], totalCredits: 5 },
        ],
      },
      {
        id: "da-cert",
        name: "Dental Assisting",
        award: "Certificate",
        categoryId: "healthcare",
        totalCredits: 50,
        years: 1,
        description: "Prepare for chairside dental assisting in a one-year accelerated program",
        courses: HEALTH_COURSES.filter(c => c.code.startsWith("DA")),
        prereqGroups: [
          { type: "English", description: "Oral and written communication", minCredits: 5, options: ["ENGL 101"] },
          { type: "Biology", description: "Human biology or anatomy", minCredits: 5, options: ["BIOL 101"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["DA 100", "DA 110", "MA 101"], totalCredits: 15 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["DA 120", "DA 130", "DA 140"], totalCredits: 11 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["DA 200", "DA 250"], totalCredits: 10 },
        ],
      },
      {
        id: "nurs-aas",
        name: "Nursing",
        award: "AAS",
        categoryId: "healthcare",
        totalCredits: 100,
        years: 2,
        description: "RN preparation program accredited by ACEN, leading to NCLEX-RN licensure",
        courses: [...HEALTH_COURSES.filter(c => c.code.startsWith("NURS")), ...GENED_COURSES.slice(0, 5)],
        prereqGroups: [
          { type: "Anatomy & Physiology", description: "A&P I and II required", minCredits: 10, options: ["BIOL 101"] },
          { type: "English", description: "College-level composition", minCredits: 5, options: ["ENGL 101", "ENGL&101"] },
          { type: "Microbiology", description: "Microbiology with lab", minCredits: 5, options: ["BIOL 101"] },
          { type: "Nutrition", description: "Human nutrition", minCredits: 3, options: ["BIOL 101"] },
          { type: "Psychology", description: "General psychology", minCredits: 5, options: ["PSYC 100", "PSYC&100"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["NURS 100", "MA 101"], totalCredits: 13 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["NURS 110", "NURS 120"], totalCredits: 13 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["NURS 130", "NURS 140"], totalCredits: 10 },
          { year: 2, season: "Fall",   monthRange: "Sep–Nov", courses: ["NURS 200", "COMM 101"], totalCredits: 13 },
          { year: 2, season: "Winter", monthRange: "Jan–Mar", courses: ["NURS 210", "NURS 220"], totalCredits: 10 },
          { year: 2, season: "Spring", monthRange: "Apr–Jun", courses: ["NURS 250"], totalCredits: 5 },
        ],
      },
      {
        id: "phrm-cert",
        name: "Pharmacy Technician",
        award: "Certificate",
        categoryId: "healthcare",
        totalCredits: 48,
        years: 1,
        description: "Preparation for pharmacy technician certification (PTCE) in retail and hospital settings",
        courses: HEALTH_COURSES.filter(c => c.code.startsWith("PHRM")),
        prereqGroups: [
          { type: "English", description: "Communication requirement", minCredits: 5, options: ["ENGL 101"] },
          { type: "Math", description: "Drug dosage calculation readiness", minCredits: 5, options: ["MATH 107"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["PHRM 100", "MA 101", "MATH 107"], totalCredits: 13 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["PHRM 110", "PHRM 120"], totalCredits: 8 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["PHRM 130", "PHRM 200"], totalCredits: 10 },
        ],
      },
    ],
  },

  // ── 4. Applied Technology & Trades ────────────────────────────────────────
  {
    id: "applied-tech",
    name: "Applied Technology & Trades",
    icon: "⚡",
    description: "Electrical, welding, HVAC/R, and skilled trades programs",
    programs: [
      {
        id: "elet-aas",
        name: "Electrical Technology",
        award: "AAS",
        categoryId: "applied-tech",
        totalCredits: 90,
        years: 2,
        description: "Comprehensive electrical training from residential wiring through industrial systems",
        courses: [...TECH_COURSES.filter(c => c.code.startsWith("ELET")), ...GENED_COURSES.slice(0, 3)],
        prereqGroups: [
          { type: "Math", description: "Algebra for electrical calculations", minCredits: 5, options: ["MATH 107", "MATH 141"] },
          { type: "English", description: "Technical writing", minCredits: 5, options: ["ENGL 101"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["ELET 101", "ELET 110", "MATH 107"], totalCredits: 15 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["ELET 102", "ELET 120"], totalCredits: 10 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["ELET 130", "ENGL 101"], totalCredits: 10 },
          { year: 2, season: "Fall",   monthRange: "Sep–Nov", courses: ["ELET 140", "ELET 200"], totalCredits: 10 },
          { year: 2, season: "Winter", monthRange: "Jan–Mar", courses: ["ELET 210", "COMM 101"], totalCredits: 10 },
          { year: 2, season: "Spring", monthRange: "Apr–Jun", courses: ["ELET 250"], totalCredits: 5 },
        ],
      },
      {
        id: "weld-aas",
        name: "Welding Technology",
        award: "AAS",
        categoryId: "applied-tech",
        totalCredits: 83,
        years: 2,
        description: "Full welding technician program covering SMAW, GMAW, GTAW, and pipe welding",
        courses: [...TECH_COURSES.filter(c => c.code.startsWith("WELD")), ...GENED_COURSES.slice(0, 3)],
        prereqGroups: [
          { type: "Math", description: "Blueprint math proficiency", minCredits: 5, options: ["MATH 107"] },
          { type: "English", description: "Technical communication", minCredits: 5, options: ["ENGL 101"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["WELD 101", "WELD 110", "WELD 140"], totalCredits: 10 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["WELD 120", "MATH 107", "ENGL 101"], totalCredits: 15 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["WELD 130", "COMM 101"], totalCredits: 10 },
          { year: 2, season: "Fall",   monthRange: "Sep–Nov", courses: ["WELD 200", "PSYC 100"], totalCredits: 10 },
          { year: 2, season: "Winter", monthRange: "Jan–Mar", courses: ["WELD 210"], totalCredits: 5 },
          { year: 2, season: "Spring", monthRange: "Apr–Jun", courses: ["WELD 250"], totalCredits: 3 },
        ],
      },
      {
        id: "hvac-cert",
        name: "HVAC/R Technology",
        award: "Certificate",
        categoryId: "applied-tech",
        totalCredits: 55,
        years: 1,
        description: "Residential and light commercial HVAC/R installation, service, and EPA 608 certification",
        courses: TECH_COURSES.filter(c => c.code.startsWith("HVAC")),
        prereqGroups: [
          { type: "Math", description: "HVAC calculation readiness", minCredits: 5, options: ["MATH 107"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["HVAC 100", "HVAC 110", "MATH 107"], totalCredits: 15 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["HVAC 120", "HVAC 140"], totalCredits: 8 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["HVAC 130", "HVAC 200"], totalCredits: 10 },
        ],
      },
    ],
  },

  // ── 5. Automotive Technology ───────────────────────────────────────────────
  {
    id: "automotive",
    name: "Automotive Technology",
    icon: "🚗",
    description: "Automotive service technology including ASE certification pathways",
    programs: [
      {
        id: "auto-aas",
        name: "Automotive Service Technology",
        award: "AAS",
        categoryId: "automotive",
        totalCredits: 91,
        years: 2,
        description: "ASE-aligned automotive service training for employment in dealerships and independent shops",
        courses: [...AUTO_COURSES, ...GENED_COURSES.slice(0, 3)],
        prereqGroups: [
          { type: "Math", description: "Technical math proficiency", minCredits: 5, options: ["MATH 107"] },
          { type: "English", description: "Technical communication", minCredits: 5, options: ["ENGL 101"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["AUTO 101", "MATH 107", "ENGL 101"], totalCredits: 15 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["AUTO 110", "AUTO 120"], totalCredits: 10 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["AUTO 130", "AUTO 140", "COMM 101"], totalCredits: 13 },
          { year: 2, season: "Fall",   monthRange: "Sep–Nov", courses: ["AUTO 150", "AUTO 200"], totalCredits: 10 },
          { year: 2, season: "Winter", monthRange: "Jan–Mar", courses: ["AUTO 210", "AUTO 220"], totalCredits: 10 },
          { year: 2, season: "Spring", monthRange: "Apr–Jun", courses: ["AUTO 250"], totalCredits: 5 },
        ],
      },
      {
        id: "auto-cert",
        name: "Automotive Service Technology",
        award: "Certificate",
        categoryId: "automotive",
        totalCredits: 46,
        years: 1,
        description: "Entry-level automotive service skills covering brakes, suspension, electrical, and engine basics",
        courses: AUTO_COURSES.filter(c => parseInt(c.code.split(" ")[1]) < 150),
        prereqGroups: [
          { type: "Math", description: "Basic automotive math", minCredits: 5, options: ["MATH 107"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["AUTO 101", "MATH 107"], totalCredits: 10 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["AUTO 110", "AUTO 120"], totalCredits: 10 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["AUTO 130", "AUTO 140"], totalCredits: 8 },
        ],
      },
    ],
  },

  // ── 6. Culinary Arts & Hospitality ─────────────────────────────────────────
  {
    id: "culinary",
    name: "Culinary Arts & Hospitality",
    icon: "🍳",
    description: "Culinary arts, baking & pastry, and hospitality management programs",
    programs: [
      {
        id: "culn-aas",
        name: "Culinary Arts",
        award: "AAS",
        categoryId: "culinary",
        totalCredits: 91,
        years: 2,
        description: "Professional culinary training from techniques through restaurant management",
        courses: [...CULN_COURSES.filter(c => c.code.startsWith("CULN")), ...GENED_COURSES.slice(0, 4)],
        prereqGroups: [
          { type: "English", description: "Communication skills", minCredits: 5, options: ["ENGL 101"] },
          { type: "Food Safety", description: "ServSafe certification (can be concurrent)", minCredits: 3, options: ["CULN 140"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["CULN 101", "CULN 140", "ENGL 101"], totalCredits: 13 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["CULN 110", "CULN 130", "MATH 107"], totalCredits: 13 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["CULN 120", "CULN 150"], totalCredits: 10 },
          { year: 2, season: "Fall",   monthRange: "Sep–Nov", courses: ["CULN 200", "COMM 101"], totalCredits: 10 },
          { year: 2, season: "Winter", monthRange: "Jan–Mar", courses: ["CULN 210", "PSYC 100"], totalCredits: 10 },
          { year: 2, season: "Spring", monthRange: "Apr–Jun", courses: ["CULN 250"], totalCredits: 5 },
        ],
      },
      {
        id: "bake-cert",
        name: "Baking & Pastry Arts",
        award: "Certificate",
        categoryId: "culinary",
        totalCredits: 46,
        years: 1,
        description: "Professional baking and pastry skills for bakeries, hotels, and restaurants",
        courses: CULN_COURSES.filter(c => c.code.startsWith("BAKE") || c.code === "CULN 140"),
        prereqGroups: [],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["CULN 140", "BAKE 101"], totalCredits: 8 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["BAKE 110", "BAKE 120"], totalCredits: 10 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["BAKE 130", "BAKE 200", "BAKE 250"], totalCredits: 11 },
        ],
      },
    ],
  },

  // ── 7. Construction & Trades ───────────────────────────────────────────────
  {
    id: "construction",
    name: "Construction Technology",
    icon: "🔨",
    description: "Carpentry, construction technology, and skilled trades programs",
    programs: [
      {
        id: "carp-aas",
        name: "Construction Technology",
        award: "AAS",
        categoryId: "construction",
        totalCredits: 90,
        years: 2,
        description: "Comprehensive construction technology program covering framing through project management",
        courses: [...CONST_COURSES, ...GENED_COURSES.slice(0, 3)],
        prereqGroups: [
          { type: "Math", description: "Construction math proficiency", minCredits: 5, options: ["MATH 107"] },
          { type: "English", description: "Technical communication", minCredits: 5, options: ["ENGL 101"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["CARP 100", "CARP 120", "MATH 107"], totalCredits: 13 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["CARP 110", "ENGL 101"], totalCredits: 10 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["CARP 130", "CARP 150", "COMM 101"], totalCredits: 15 },
          { year: 2, season: "Fall",   monthRange: "Sep–Nov", courses: ["CARP 140", "PSYC 100"], totalCredits: 10 },
          { year: 2, season: "Winter", monthRange: "Jan–Mar", courses: ["CARP 200"], totalCredits: 5 },
          { year: 2, season: "Spring", monthRange: "Apr–Jun", courses: ["CARP 210", "CARP 250"], totalCredits: 8 },
        ],
      },
      {
        id: "carp-cert",
        name: "Carpentry",
        award: "Certificate",
        categoryId: "construction",
        totalCredits: 43,
        years: 1,
        description: "Entry-level carpentry skills including framing, finish, and blueprint reading",
        courses: CONST_COURSES.filter(c => parseInt(c.code.split(" ")[1]) <= 140),
        prereqGroups: [
          { type: "Math", description: "Basic construction math", minCredits: 5, options: ["MATH 107"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["CARP 100", "CARP 120", "MATH 107"], totalCredits: 13 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["CARP 110", "CARP 150"], totalCredits: 10 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["CARP 130", "CARP 140"], totalCredits: 10 },
        ],
      },
    ],
  },

  // ── 8. Transfer Education ──────────────────────────────────────────────────
  {
    id: "transfer",
    name: "Transfer / General Education",
    icon: "🎓",
    description: "Associate degrees designed for transfer to 4-year universities",
    programs: [
      {
        id: "aa-transfer",
        name: "Associate of Arts (AA) Transfer",
        award: "AA",
        categoryId: "transfer",
        totalCredits: 90,
        years: 2,
        description: "Direct transfer degree accepted at all Washington State public four-year universities",
        courses: TRANSFER_COURSES,
        prereqGroups: [
          { type: "English Composition", description: "Two-course English sequence", minCredits: 10, options: ["ENGL&101", "ENGL&102"] },
          { type: "Quantitative/Symbolic Reasoning", description: "Math 107 or higher", minCredits: 5, options: ["MATH&107", "MATH&141", "MATH&142", "MATH&151"] },
          { type: "Natural Sciences", description: "Two courses with lab", minCredits: 10, options: ["BIOL&211", "CHEM&121"] },
          { type: "Social Sciences", description: "Two different disciplines", minCredits: 10, options: ["PSYC&100", "SOCY&101", "POLS&202", "ECON&201", "ECON&202"] },
          { type: "Humanities", description: "Two courses from arts, humanities, or language", minCredits: 10, options: ["HIST&111", "HIST&112", "PHIL&101", "ART&101", "MUSC&141"] },
          { type: "Health & PE", description: "Health/wellness course", minCredits: 2, options: ["PE&101"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["ENGL&101", "MATH&141", "PSYC&100"], totalCredits: 15 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["ENGL&102", "HIST&111", "SOCY&101"], totalCredits: 15 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["COMM&101", "POLS&202", "PE&101"], totalCredits: 12 },
          { year: 2, season: "Fall",   monthRange: "Sep–Nov", courses: ["MATH&142", "BIOL&211", "PHIL&101"], totalCredits: 15 },
          { year: 2, season: "Winter", monthRange: "Jan–Mar", courses: ["ECON&201", "HIST&112", "MUSC&141"], totalCredits: 15 },
          { year: 2, season: "Spring", monthRange: "Apr–Jun", courses: ["MATH&151", "ECON&202"], totalCredits: 10 },
        ],
      },
      {
        id: "as-business",
        name: "Associate of Science: Business (AS-T)",
        award: "AAS-T",
        categoryId: "transfer",
        totalCredits: 90,
        years: 2,
        description: "Transfer degree for students planning to continue into a 4-year Business program",
        courses: [...TRANSFER_COURSES, ...BUS_COURSES.slice(0, 5)],
        prereqGroups: [
          { type: "English", description: "College composition sequence", minCredits: 10, options: ["ENGL&101", "ENGL&102"] },
          { type: "Math", description: "Precalculus minimum", minCredits: 5, options: ["MATH&141", "MATH&142"] },
          { type: "Economics", description: "Micro and Macro Economics", minCredits: 10, options: ["ECON&201", "ECON&202"] },
          { type: "Social Science", description: "Behavioral science distribution", minCredits: 5, options: ["PSYC&100", "SOCY&101"] },
        ],
        quarterPlan: [
          { year: 1, season: "Fall",   monthRange: "Sep–Nov", courses: ["ENGL&101", "MATH&141", "BUSA 100"], totalCredits: 13 },
          { year: 1, season: "Winter", monthRange: "Jan–Mar", courses: ["ENGL&102", "ECON&201", "ACCT 101"], totalCredits: 15 },
          { year: 1, season: "Spring", monthRange: "Apr–Jun", courses: ["MATH&142", "ECON&202", "PSYC&100"], totalCredits: 15 },
          { year: 2, season: "Fall",   monthRange: "Sep–Nov", courses: ["BUSA 110", "POLS&202", "HIST&111"], totalCredits: 15 },
          { year: 2, season: "Winter", monthRange: "Jan–Mar", courses: ["BUSA 120", "COMM&101", "SOCY&101"], totalCredits: 15 },
          { year: 2, season: "Spring", monthRange: "Apr–Jun", courses: ["ACCT 102", "BUSA 115"], totalCredits: 10 },
        ],
      },
    ],
  },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Look up a course by code across all categories */
export function findCourse(code: string): RtcCourse | undefined {
  for (const cat of RTC_CAREER_CATEGORIES) {
    for (const prog of cat.programs) {
      const c = prog.courses.find((x) => x.code === code);
      if (c) return c;
    }
  }
  return undefined;
}

/** Get all unique programs as a flat list */
export function allPrograms(): RtcProgram[] {
  return RTC_CAREER_CATEGORIES.flatMap((c) => c.programs);
}

/** Get a program by id */
export function findProgram(id: string): RtcProgram | undefined {
  return allPrograms().find((p) => p.id === id);
}

/** Get all courses for a program including general-ed equivalents */
export function programCourseMap(prog: RtcProgram): Map<string, RtcCourse> {
  const map = new Map<string, RtcCourse>();
  prog.courses.forEach((c) => map.set(c.code, c));
  return map;
}

/** Compute the calendar start year based on next available quarter from today */
export function calendarStartYear(today: Date, startSeason: "Fall" | "Winter" | "Spring" | "Summer"): number {
  const month = today.getMonth() + 1;
  const year = today.getFullYear();
  if (startSeason === "Fall")   return month >= 9 ? year + 1 : year;
  if (startSeason === "Winter") return month >= 1 && month < 7 ? year : year + 1;
  if (startSeason === "Spring") return month >= 4 ? year : year;
  return year;
}

/** Compute actual calendar year for a QuarterSlot given the base year */
export function slotCalendarYear(slot: QuarterSlot, baseYear: number): number {
  // Year 1 Fall = baseYear; Year 1 Winter/Spring = baseYear + 1 (if base is Fall)
  // For simplicity: Y1 Fall = baseYear, Y1 Winter = baseYear+0 (same acad year), Spring = baseYear+0
  // Academic year: Fall -> Winter -> Spring -> (Summer) -> next Fall
  if (slot.season === "Fall") return baseYear + (slot.year - 1);
  return baseYear + (slot.year - 1);
}

/** Season to months label */
export const SEASON_MONTHS: Record<string, string> = {
  Fall:   "Sep – Nov",
  Winter: "Jan – Mar",
  Spring: "Apr – Jun",
  Summer: "Jul – Aug",
};

/** All unique award types */
export const AWARD_TYPES = ["AAS", "AA", "AS", "AAS-T", "AAT", "BAS", "Certificate", "Short Certificate"] as const;
