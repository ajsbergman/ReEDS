/** Shared LLM provider definitions used across Settings and Welcome screens. */

export interface ModelDef {
  value: string;
  label: string;
}

export interface ProviderDef {
  value: string;
  label: string;
  icon: string;
  desc: string;
  placeholder: string;
  models: ModelDef[];
  helpUrl: string;
}

export const PROVIDERS: ProviderDef[] = [
  {
    value: "anthropic",
    label: "Anthropic (Claude)",
    icon: "🟣",
    desc: "Claude models",
    placeholder: "sk-ant-api03-…",
    models: [
      { value: "claude-opus-4-1", label: "Claude Opus 4.1" },
      { value: "claude-sonnet-4-1", label: "Claude Sonnet 4.1" },
      { value: "claude-sonnet-4-0", label: "Claude Sonnet 4" },
      { value: "claude-haiku-4", label: "Claude Haiku 4" },
      { value: "claude-3-5-sonnet-20241022", label: "Claude 3.5 Sonnet" },
    ],
    helpUrl: "https://console.anthropic.com/settings/keys",
  },
  {
    value: "openai",
    label: "OpenAI (GPT)",
    icon: "🟢",
    desc: "GPT models",
    placeholder: "sk-…",
    models: [
      { value: "gpt-4o", label: "GPT-4o" },
      { value: "gpt-4o-mini", label: "GPT-4o Mini" },
      { value: "gpt-4-turbo", label: "GPT-4 Turbo" },
      { value: "o3", label: "o3" },
      { value: "o4-mini", label: "o4-mini" },
    ],
    helpUrl: "https://platform.openai.com/api-keys",
  },
  {
    value: "google",
    label: "Google (Gemini)",
    icon: "🔵",
    desc: "Gemini models",
    placeholder: "AIza…",
    models: [
      { value: "gemini-2.5-flash", label: "Gemini 2.5 Flash" },
      { value: "gemini-2.5-pro", label: "Gemini 2.5 Pro" },
      { value: "gemini-3-flash-preview", label: "Gemini 3 Flash (Preview)" },
      { value: "gemini-3-pro-preview", label: "Gemini 3 Pro (Preview)" },
      { value: "gemini-2.5-flash-lite", label: "Gemini 2.5 Flash Lite" },
    ],
    helpUrl: "https://aistudio.google.com/app/apikey",
  },
  {
    value: "nlr",
    label: "NLR LiteLLM",
    icon: "🏢",
    desc: "NLR internal proxy (free for NLR staff)",
    placeholder: "sk-…",
    models: [
      { value: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
      { value: "claude-opus-4-7", label: "Claude Opus 4.7" },
      { value: "claude-opus-4-6", label: "Claude Opus 4.6" },
      { value: "claude-haiku-4-5", label: "Claude Haiku 4.5" },
      { value: "gpt-5.4", label: "GPT-5.4" },
      { value: "gpt-5.3-codex", label: "GPT-5.3 Codex" },
      { value: "gpt-5-mini", label: "GPT-5 Mini" },
      { value: "gemini-3.1-pro-preview", label: "Gemini 3.1 Pro (Preview)" },
      { value: "gemini-3-pro-image-preview", label: "Gemini 3 Pro Image (Preview)" },
    ],
    helpUrl: "https://cloud.nlr.gov/",
  },
];
