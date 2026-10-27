// Editor designs retain every valid skill. These are game installation limits.
export function skillCapacityNotice(project) {
  const innate = project.innate_skills?.length ?? 0;
  const additional = project.additional_skills?.length ?? 0;
  if (innate <= 100 && additional <= 100) return '';
  return `已完整保留天生 ${innate} 项、追加 ${additional} 项，可继续编辑、保存和分享工程。当前游戏实装与显示支持天生 100 项、追加 100 项；生成 APK 前请调整数量。`;
}
