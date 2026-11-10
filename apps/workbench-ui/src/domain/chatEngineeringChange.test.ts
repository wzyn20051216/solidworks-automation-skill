import { describe, expect, it } from "vitest";
import { classifyChatEngineeringChange } from "./chatEngineeringChange";

describe("对话工程变更识别", () => {
  it.each([
    ["请把宽度从 60 改成 80 mm", ["part-modeling"]],
    ["长改到120，宽度不变", ["part-modeling"]],
    ["把沉孔直径改为 12 mm", ["holes-fillet-chamfer"]],
    ["把 M6 螺纹改成 M8", ["holes-fillet-chamfer"]],
    ["把 M6 改成 M8，其他尺寸不变", ["holes-fillet-chamfer"]],
    ["孔径改大 2 mm", ["holes-fillet-chamfer"]],
    ["把这个外壳的 USB 口改大 1mm，并重新导出 STL 和国标 PDF 图纸", ["holes-fillet-chamfer"]],
    ["孔径增加 2 mm；配合间隙改成 0.4 mm", ["holes-fillet-chamfer", "assembly-mates"]],
    ["图纸标注公差改为 ±0.05 mm", ["drawing-bom"]],
    ["别改长度，宽度改到 80 mm", ["part-modeling"]],
    ["需求改成用于潮湿环境。孔径设为 8mm", ["requirements"]],
    ["把材料换成铝合金，其他不变", ["requirements"]],
    ["把宽度改为“80 mm”", ["part-modeling"]],
    ["把材料改成“铝合金”", ["requirements"]],
    ["把壁厚改成2.5mm。原先用的是多厚？", ["part-modeling"]],
    ["Change the hole diameter from 6 to 8 mm.", ["holes-fillet-chamfer"]],
    ["Set the wall thickness to 2 mm.", ["part-modeling"]],
  ])("识别明确改动 %s", (message, roots) => {
    expect(classifyChatEngineeringChange(message)).toEqual(roots);
  });

  it.each([
    "之前的宽度是多少？",
    "把长度改为120会不会更难制造？",
    "能否把孔径改成 8 mm",
    "请说明把宽度改为80会造成什么影响",
    "如果空间够，就把宽度改成 100 mm",
    "不要把长度改成 120",
    "宽度可以改成80",
    "我已经把宽度改成80",
    "请解释这句：“把宽度改成 80 mm”",
    "“把宽度改成80”",
    "记录这句话：“这是示例，把孔径改成 8 mm”",
    "对比不同材料、尺寸与载荷",
    "导出为 STEP 后再发给我",
    "What if we change the width to 80 mm?",
    "Don't change the width to 80 mm.",
    "Could you explain whether to change the width to 80 mm?",
  ])("跳过普通追问、假设和否定 %s", (message) => {
    expect(classifyChatEngineeringChange(message)).toEqual([]);
  });
});
