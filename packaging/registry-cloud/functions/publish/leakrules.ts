// The same tripwire as agentos/agentbundle.py _LEAK_RULES, so the registry
// refuses what a Bento would have refused. tests/test_registry_cloud.py fails
// when the two lists differ.
export const LEAK_RULES: [string, string, string][] = [
  ["an Anthropic API key", "sk-ant-[A-Za-z0-9_-]{10,}", ""],
  ["an OpenAI-style API key", "sk-[A-Za-z0-9]{20,}", ""],
  ["a GitHub token", "gh[pousr]_[A-Za-z0-9]{20,}", ""],
  ["a Slack token", "xox[baprs]-[A-Za-z0-9-]{10,}", ""],
  ["an AWS access key id", "AKIA[0-9A-Z]{16}", ""],
  ["a Google API key", "AIza[0-9A-Za-z_-]{30,}", ""],
  ["a private key block", "-----BEGIN [A-Z ]*PRIVATE KEY-----", ""],
  ["a Telegram bot token", "\\b\\d{8,10}:[A-Za-z0-9_-]{30,}\\b", ""],
  ["a bearer credential", "bearer\\s+[A-Za-z0-9._\\-]{20,}", "i"],
  ["a field named like a credential",
   "\\\"(api_key|apikey|secret|token|password|passwd|private_key)\\\"\\s*:\\s*\\\"[^\\\"<>{}]{8,}\\\"", "i"],
];
