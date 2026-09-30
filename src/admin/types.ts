export interface Admin {
  id: number | null;
  name: string;
  email: string;
}

export interface Session {
  admin: Admin;
  csrf_token: string | null;
}

export type InvitationStatus = 'sent' | 'opened' | 'in_progress' | 'completed' | 'expired' | 'revoked';

export interface Invitation {
  id: string;
  employee_name: string;
  email: string | null;
  employee_code: string;
  department: string | null;
  status: InvitationStatus;
  link: string;
  created_at: string;
  expires_at: string;
  opened_at: string | null;
  started_at: string | null;
  submitted_at: string | null;
  submitted_late: boolean;
  assessment_id: string | null;
}

export interface AssessmentRow {
  assessment_id: string;
  test_taker_id: string;
  name: string;
  submitted_at: string;
  status: 'Completed' | 'Incomplete';
  response_quality: 'Genuine' | 'Questionable';
  has_premium: boolean;
  strengths: string[];
  areas_of_development: string[];
}

export interface DimensionScore {
  category: string;
  sten_score: number;
  level: 'Low' | 'Moderate' | 'High';
  percentile: number;
  raw_score: number;
  interpretation: string;
}

export interface GeneratedBy {
  provider: string;
  provider_label: string;
  model: string;
  source: string;
}

export interface PremiumFeatures {
  executive_summary?: string;
  development_plan?: { dimension: string; actions: string[] }[];
  coaching_insights?: string[];
  dimension_insights?: Record<string, string>;
  content_source?: 'llm' | 'fallback' | 'mixed';
  generated_by?: GeneratedBy | null;
  error?: string;
}

export interface Report {
  assessment_id: string;
  test_id: string;
  name: string;
  submitted_at: string;
  status: string;
  response_quality: string;
  quality_flags: string[];
  questions_answered: number;
  norms: string;
  scoring_key: string;
  scores: Record<string, DimensionScore>;
  strengths: string[];
  areas_of_development: string[];
  profile_summary: string;
  premium_features?: PremiumFeatures;
}

export interface Analytics {
  assessments: {
    total: number;
    by_status: Record<string, number>;
    by_quality: Record<string, number>;
    premium_reports: number;
    avg_scoring_time_ms: number | null;
  };
  dimensions: Record<string, { n: number; mean_sten: number; min_sten: number; max_sten: number;
    levels: Record<string, number> }>;
  sten_distribution: Record<string, number>;
  engine: {
    llm_available: boolean;
    llm: { provider_label: string | null; model: string | null };
    api_calls: number;
    estimated_cost_usd: number;
    cache: { hit_rate: number | null };
  };
  norms: string;
}

export interface CohortReport {
  summary: string;
  observations: string[];
  recommendations: string[];
  content_source: 'llm' | 'fallback';
  generated_by: GeneratedBy | null;
  candidates: number;
}

export interface Provider {
  id: string;
  label: string;
  base_url: string | null;
  model_hint: string;
  key_hint: string;
  requires_key: boolean;
  base_url_editable: boolean;
  docs_url: string;
}

export interface LlmStatus {
  available: boolean;
  provider: string | null;
  provider_label: string | null;
  model: string | null;
  source: 'dashboard' | 'environment' | 'none';
  key_hint: string | null;
  base_url: string | null;
  input_price_per_mtok: number;
  output_price_per_mtok: number;
}
