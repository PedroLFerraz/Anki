export interface CardFields {
  [key: string]: string;
}

export interface Card {
  id: number;
  deck_type: string;
  fields: CardFields;
  image_filename: string | null;
  audio_filename: string | null;
  status: string;
  source_topic: string | null;
  created_at: string | null;
}

export interface DeckType {
  name: string;
  fields_schema: FieldSchema[];
}

export interface FieldSchema {
  name: string;
  type: string;
}

export interface GenerateRequest {
  topic: string;
  count: number;
  deck_type: string;
}

export interface ArtistRequest {
  artist_name: string;
  deck_type: string;
  limit: number;
}

export interface GenerateResponse {
  run_id?: number;
  persona?: string;
  gap_analysis?: string;
  cards: GeneratedCard[];
  error?: string;
  total_found?: number;
  skipped?: number;
  new?: number;
  message?: string;
}

export interface GeneratedCard {
  id: number;
  fields: CardFields;
  status: string;
  duplicate_reason?: string | null;
  has_free_image?: boolean;
  image_filename?: string | null;
}

export interface ExportRequest {
  card_ids: number[];
  deck_name: string;
}

export interface FetchMediaResult {
  image: string | null;
  audio: string | null;
  copyrighted: boolean;
  search_url?: string;
}

export interface AnalyticsRow {
  topic: string;
  deck_type: string;
  total_cards: number;
  accepted: number;
  rejected: number;
}
