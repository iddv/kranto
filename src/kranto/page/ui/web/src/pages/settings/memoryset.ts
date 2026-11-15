// service.memory, on Settings › System › Service: the memory Kranto's service runs under.
// One read, one write: the server's /api/settings/service ({memory: <GB> | "auto"}); applied at once.
export const SERVICE_SETTINGS = "/api/settings/service";
export interface ServiceMemory {
  /** the GB of MemoryMax a drop-in sets, or "auto" (from this machine's memory) */
  setting: number | "auto";
  by_hand: boolean;
  high_mb: number | null;
  max_mb: number | null;
  used_mb: number | null;
  ram_mb: number | null;
  default_high_mb: number | null;
  default_max_mb: number | null;
  /** this server is Kranto's own service: only then can it be changed here */
  applies: boolean;
  range_gb: [number, number];
  words: string;
}
const gb = (mb: number | null | undefined): string => (mb == null ? "–" : mb >= 1024 ? `${(mb / 1024).toFixed(mb % 1024 ? 1 : 0)} GB` : `${mb} MB`);
export const memoryCaps = (m: Pick<ServiceMemory, "high_mb" | "max_mb">): string =>
  m.max_mb == null ? "no cap" : `${gb(m.high_mb)} high, ${gb(m.max_mb)} at most`;
export const memoryWords = (m: ServiceMemory): string =>
  [m.setting === "auto" ? "Auto" : `${m.setting} GB`, memoryCaps(m), m.used_mb != null ? `uses ${gb(m.used_mb)} now` : null].filter(Boolean).join(" · ");
export const memoryDefault = (m: ServiceMemory): string =>
  `Auto is ${gb(m.default_max_mb)} at most on this machine (${gb(m.ram_mb)} of memory)`;
export { gb as memGb };
