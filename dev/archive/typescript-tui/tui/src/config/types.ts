export interface UrikaConfig {
  projectName: string;
  question: string;
  mode: string;
  defaultModel: string;
  models: Record<string, string>;
  privacyMode: string;
  localRoles: string[];
}
