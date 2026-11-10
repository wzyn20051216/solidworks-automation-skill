import type { EngineeringChangeRoot } from "../types";

export const engineeringChangeRoots: readonly EngineeringChangeRoot[] = [
  "requirements", "part-modeling", "holes-fillet-chamfer", "assembly-mates", "drawing-bom",
];

const targets: ReadonlyArray<readonly [EngineeringChangeRoot, RegExp]> = [
  ["requirements", /需求|要求|目标|材料|材质|载荷|工况|工艺|标准|数量|\b(?:requirements?|design goal|material|load|process|standard|quantity)\b/i],
  ["drawing-bom", /(?:工程图|图纸).*(?:公差|尺寸|标注)|\bdrawing\b.*\b(?:tolerance|dimensions?|scale)\b/i],
  ["assembly-mates", /装配.*(?:间隙|距离|尺寸|偏移)|配合.*(?:间隙|距离|偏移)|\b(?:assembly|mate|fit)\b.*\b(?:clearance|offset|distance|dimension)\b/i],
  ["holes-fillet-chamfer", /孔径|孔深|孔距|孔宽|孔$|孔.*(?:直径|深度|间距|尺寸|位置)|接口|开口|USB\s*口|螺纹|\bM\d+(?:\.\d+)?\b|(?:槽|圆角|倒角).*(?:尺寸|宽|深|半径|长度|角度)|\b(?:hole|bore|thread|slot|fillet|chamfer)\b/i],
  ["part-modeling", /(?:长|宽|高)(?:度)?$|长度|宽度|高度|厚度|壁厚|外径|内径|直径|半径|中心距|尺寸|包络|\b(?:length|width|height|thickness|diameter|radius|envelope|dimensions?)\b/i],
];

const chineseEdit = /^(?:请(?:帮我)?|帮我|现在|这次|这版|就)?\s*(?:把|将)?\s*([^，,：:]{1,60}?)(?:从[^，,：:]{1,24}?)?(?:改成|改为|改到|改至|改用|换成|换为|调整为|调整到|调整至|设为|设置为|设成|变更为|更改为|增加到|减少到|加大到|缩小到|增至|减至|加厚到|减薄到|改大|改小|增加|减少|加大|缩小|加厚|减薄)\s*(.+)$/;
const englishEdit = /^(?:please\s+)?(?:change|set|update|switch|increase|decrease|reduce|adjust)\s+(.{1,80}?)(?:\s+from\s+.{1,30}?)?\s+(?:to|by)\s+(.+)$/i;
const inquiryOrCondition = /(?:为什么|怎么样|如何|怎么做|是否|能否|能不能|可不可以|行不行|可以吗|有没有|怎么办|会怎样|会不会|会有什么|会造成|有哪些|可行吗|吗\s*$|\b(?:what if|how (?:do|can|to|would|should)|would it|could i|can i|whether)\b)|^(?:(?:请|帮我)?(?:说明|解释|分析|讨论|检查|比较|查询|评估|确认|看看)|请问|告诉我|想知道|如果|假如|假设|若|例如|比如|建议|考虑|(?:if|suppose|imagine|for example|explain|compare)\b)/i;
const negation = /^(?:请)?(?:先别|先不要|别|不要|不用|无需|不必|不改|不需要|暂不|(?:do not|don't|never|without)\b)/i;
const dimensionValue = /^(?:约|大约|大概|至少|最多|大于|小于|不超过|不低于|约为|about\s+|at least\s+)?\s*[ØφΦ∅±+\-]?\s*(?:M\s*)?\d|^(?:大|小|厚|薄|宽|窄|长|短)(?:一些|一点)/i;

export function classifyChatEngineeringChange(message: string): EngineeringChangeRoot[] {
  const roots = new Set<EngineeringChangeRoot>();
  const text = message.normalize("NFKC")
    .replace(/```[\s\S]*?```/g, "")
    .replace(/“[^”]*”|‘[^’]*’|「[^」]*」|『[^』]*』|"[^"\n]*"|`[^`\n]*`/g, (quoted) => {
      const value = quoted.slice(1, -1).trim();
      // Keep quoted measurements usable as values without treating quoted sentences as instructions.
      return /^[ØφΦ∅±+\-]?\s*M?\d+(?:\.\d+)?\s*(?:mm|cm|in|毫米|厘米|英寸|度|°)?$/i.test(value) ? value : "〈引用〉";
    });
  for (const sentence of text.match(/[^。;!?\n]+[!?]?/g) ?? []) {
    const trimmed = sentence.trim();
    // Questions, hypotheticals, examples and negated instructions are deliberately left ambiguous.
    if (!trimmed || trimmed.endsWith("?") || inquiryOrCondition.test(trimmed)) continue;
    for (const clause of trimmed.split(/[,，]/)) {
      const instruction = clause.trim();
      if (inquiryOrCondition.test(instruction) || negation.test(instruction)) continue;
      const edit = chineseEdit.exec(instruction) ?? englishEdit.exec(instruction);
      if (!edit) continue;
      const [, target, value] = edit;
      if (/不(?:把|将|再|想|需|应|要)|别|可能|可以|能够|能\s*$|应该|建议|考虑|打算|假设|前提|^[“"'‘]|^(?:我|你|他)(?:已经|曾经|之前|说|把|将)/i.test(target)) continue;
      const root = targets.find(([, pattern]) => pattern.test(target))?.[0];
      if (root && (root === "requirements" || dimensionValue.test(value))) roots.add(root);
    }
  }
  return roots.has("requirements") ? ["requirements"] : [...roots];
}
