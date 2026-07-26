const NON_DND_MARKERS = [
  "克苏鲁",
  "奈亚拉托提普",
  "犹格索托斯",
  "犹格·索托斯",
  "阿撒托斯",
  "旧日支配者",
  "深潜者",
  "san值",
  "san 值",
  "理智检定",
  "call of cthulhu",
];

export function containsNonDndContent(value: string): boolean {
  const normalized = value.toLocaleLowerCase();
  return NON_DND_MARKERS.some((marker) => normalized.includes(marker.toLocaleLowerCase()));
}

export function safeDndText(value: string | null | undefined): string {
  if (!value) return "";
  return containsNonDndContent(value)
    ? "这条历史 AI 提示含有其他规则系统的专有内容，已隔离不显示。请重新生成 D&D 5e 2024 建议。"
    : value;
}
