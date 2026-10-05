import fs from 'node:fs';
import path from 'node:path';

export interface ContentItem { id: string; slug: string; title: string; summary: string; kind: 'news'|'review'|'guide'|'issue'|'resource'; tags: string[]; sourceUrl: string; sourceName: string; publishedAt: string|null; updatedAt: string|null; evidenceStatus: string; body: string; relatedIds: string[]; environment?: string[]; }
export interface Product { id: string; name: string; manufacturer: string; model: string; distributor?: string; sourceUrl: string; specs: Record<string,string>; }
export interface PriceObservation { id: string; offerId: string; productId: string; seller: string; region: 'KR'|'US'|'EU'; currency: string; price: number|null; shipping: number|null; condition: string; stock: 'in_stock'|'out_of_stock'|'unknown'|'fetch_error'|'price_missing'; observedAt: string; sourceUrl: string; stale?: boolean; collectionEventId?: string; }
export interface Compatibility { id: string; os: string; tool: string; version: string; status: string; detail: string; sourceUrl: string; checkedAt: string; }
export interface ShowcaseItem { id: string; title: string; type: 'image'|'video'; url: string; poster?: string; description: string; provenance: 'verified-local-run'|'creator-reported'|'unverified-reference'; model?: string; tool?: string; gpuCount?: number; createdAt?: string; sourceUrl?: string; rights: string; metadata?: Record<string,string>; }
export interface SourceSummary { id: string; name: string; url: string; category: string; status: string; resourceKind?: string; automationVerified: boolean; }
export interface PublicOperations { lastRunAt: string|null; lastSuccessAt: string|null; nextRunAt: string|null; activeSources: number; sourceCount: number; state: string; notices: string[]; }
export interface SiteData { schemaVersion: 1; releaseId: string; generatedAt: string; siteUrl: string; content: ContentItem[]; products: Product[]; prices: PriceObservation[]; compatibility: Compatibility[]; showcase: ShowcaseItem[]; sources: SourceSummary[]; operations: PublicOperations; }

export function projectRoot() { return path.resolve(process.env.R9700_ROOT || process.cwd()); }
export function loadSiteData(): SiteData {
  const root = projectRoot();
  const published = process.env.SITE_DATA_PATH || path.join(root, '.local/public/site-data.json');
  const selected = fs.existsSync(published) ? published : path.join(root, 'data/site-data.json');
  const raw = JSON.parse(fs.readFileSync(selected, 'utf8').replace(/^\uFEFF/, ''));
  if (raw.schemaVersion !== 1 || typeof raw.releaseId !== 'string' || !Array.isArray(raw.content)) throw new Error('Invalid public data snapshot');
  for (const key of ['products','prices','compatibility','showcase','sources']) if (!Array.isArray(raw[key])) throw new Error('Invalid public data list');
  return raw as SiteData;
}
export function getContentBySlug(slug: string) { return loadSiteData().content.find(item => item.slug === slug); }
export function formatDate(value: string|null|undefined) {
  if (!value) return '날짜 미상';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '날짜 미상' : new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(date);
}
export function isStale(item: PriceObservation) { return item.stale === true || !Number.isFinite(Date.parse(item.observedAt)) || Date.now() - Date.parse(item.observedAt) > 12*60*60*1000; }
export function siteUrl() { return process.env.SITE || 'https://r9700.jjgo.io'; }
