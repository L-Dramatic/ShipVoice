from __future__ import annotations

import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "outputs" / "manual-20260608-shipvoice" / "presentations" / "shipvoice-final"
SLIDES_DIR = WORKSPACE / "slides"
PREVIEW_DIR = WORKSPACE / "preview"
LAYOUT_DIR = WORKSPACE / "layout"
ASSET_DIR = WORKSPACE / "assets"
OUTPUT_DIR = ROOT / "deliverables"
FINAL_PPTX = OUTPUT_DIR / "ShipVoice_Final_Defense_Deck_Draft.pptx"


THEME = r'''
export const C = {
  ink: "#121826",
  navy: "#0B2545",
  blue: "#2563EB",
  cyan: "#06B6D4",
  green: "#10B981",
  gold: "#F59E0B",
  red: "#DC2626",
  paper: "#F7F9FC",
  white: "#FFFFFF",
  muted: "#64748B",
  line: "#D8E0EA",
  softBlue: "#E8F1FF",
  softGreen: "#EAFBF3",
  softGold: "#FFF7E6",
  softRed: "#FFF1F2",
};

export function slideBg(slide, ctx, fill=C.paper) {
  ctx.addShape(slide, {x:0, y:0, w:ctx.W, h:ctx.H, fill, line:ctx.line(fill,0)});
}

export function footer(slide, ctx, label="ShipVoice | 信息安全基础 A2") {
  ctx.addText(slide, {text: label, x:52, y:672, w:760, h:22, fontSize:14, color:C.muted});
  ctx.addText(slide, {text: String(ctx.slideNumber).padStart(2,"0"), x:1180, y:672, w:48, h:22, fontSize:14, color:C.muted, align:"right"});
}

export function kicker(slide, ctx, text, x=52, y=38, color=C.blue) {
  ctx.addShape(slide, {x, y:y+8, w:34, h:4, fill:color, line:ctx.line(color,0)});
  ctx.addText(slide, {text, x:x+48, y, w:400, h:22, fontSize:15, bold:true, color, valign:"mid"});
}

export function title(slide, ctx, text, sub="", dark=false) {
  ctx.addText(slide, {text, x:52, y:72, w:980, h:88, fontSize:36, bold:true, color:dark ? C.white : C.ink, typeface:ctx.fonts.title});
  if (sub) ctx.addText(slide, {text:sub, x:54, y:154, w:980, h:32, fontSize:18, color:dark ? "#B9D6FF" : C.muted});
}

export function note(slide, ctx, text, x, y, w, h, fill=C.white, border=C.line) {
  ctx.addShape(slide, {x,y,w,h,fill,line:ctx.line(border,1)});
  ctx.addText(slide, {text,x:x+18,y:y+14,w:w-36,h:h-28,fontSize:18,color:C.ink,valign:"mid",insets:{left:0,right:0,top:0,bottom:0}});
}

export function metric(slide, ctx, value, label, x, y, w, accent=C.blue) {
  ctx.addShape(slide, {x,y,w,h:86,fill:C.white,line:ctx.line("#DDE5F0",1)});
  ctx.addShape(slide, {x,y,w:6,h:86,fill:accent,line:ctx.line(accent,0)});
  ctx.addText(slide, {text:value,x:x+22,y:y+12,w:w-36,h:34,fontSize:30,bold:true,color:accent,typeface:ctx.fonts.title});
  ctx.addText(slide, {text:label,x:x+22,y:y+50,w:w-36,h:24,fontSize:15,color:C.muted});
}

export function pill(slide, ctx, text, x, y, w, fill, color=C.ink) {
  ctx.addShape(slide, {x,y,w,h:34,fill,line:ctx.line(fill,0)});
  ctx.addText(slide, {text,x:x+12,y:y+7,w:w-24,h:20,fontSize:14,bold:true,color,align:"center"});
}

export function line(slide, ctx, x, y, w, h=2, color=C.line) {
  ctx.addShape(slide, {x,y,w,h,fill:color,line:ctx.line(color,0)});
}

export function box(slide, ctx, text, x, y, w, h, fill=C.white, accent=C.blue) {
  ctx.addShape(slide, {x,y,w,h,fill,line:ctx.line("#DDE5F0",1)});
  ctx.addShape(slide, {x,y,w:5,h,fill:accent,line:ctx.line(accent,0)});
  ctx.addText(slide, {text,x:x+18,y:y+14,w:w-34,h:h-24,fontSize:17,color:C.ink,valign:"mid"});
}
'''


SLIDES = {
    "slide-01.mjs": r'''
import { C, slideBg, pill, line } from "./theme.mjs";
export async function slide01(presentation, ctx) {
  const slide = presentation.slides.add();
  slideBg(slide, ctx, C.navy);
  ctx.addShape(slide,{x:0,y:0,w:ctx.W,h:ctx.H,fill:C.navy,line:ctx.line(C.navy,0)});
  ctx.addText(slide,{text:"ShipVoice",x:64,y:92,w:700,h:72,fontSize:60,bold:true,color:C.white,typeface:ctx.fonts.title});
  ctx.addText(slide,{text:"船厂安全实时语音问答助手",x:66,y:168,w:780,h:44,fontSize:32,bold:true,color:"#DDEBFF"});
  ctx.addText(slide,{text:"A2 级联式语音问答系统复现与改进 | 安全门控 + RAG + Qwen LoRA 实验",x:68,y:226,w:940,h:34,fontSize:20,color:"#A9C7F5"});
  line(slide,ctx,68,296,430,4,C.cyan);
  const xs=[68,298,528,758];
  const vals=[["20","知识条目"],["55","安全评测"],["0","危险误放行"],["0.168","LoRA train loss"]];
  vals.forEach((v,i)=>{ctx.addText(slide,{text:v[0],x:xs[i],y:344,w:170,h:50,fontSize:42,bold:true,color:i===1?C.green:i===3?C.gold:C.white,typeface:ctx.fonts.title}); ctx.addText(slide,{text:v[1],x:xs[i]+2,y:396,w:180,h:24,fontSize:16,color:"#B7C9E8"});});
  pill(slide,ctx,"姓名 / 学号待补充",68,608,230,"#163B68","#DDEBFF");
  ctx.addText(slide,{text:"2026-06-08",x:1010,y:612,w:190,h:28,fontSize:18,color:"#B7C9E8",align:"right"});
  return slide;
}
''',
    "slide-02.mjs": r'''
import { C, slideBg, kicker, title, footer, box, metric } from "./theme.mjs";
export async function slide02(presentation, ctx) {
  const slide = presentation.slides.add();
  slideBg(slide, ctx);
  kicker(slide,ctx,"PROBLEM");
  title(slide,ctx,"船厂安全问答不能只做“语音转文字 + 大模型”","高风险作业场景需要领域术语、审批约束和拒答边界。");
  box(slide,ctx,"术语密集：密闭舱室、舾装、管路试压、分段吊装等问题需要专业语境。",68,210,350,126,C.white,C.blue);
  box(slide,ctx,"安全关键：错误建议可能诱导跳过审批、检测、监护或消防准备。",464,210,350,126,C.white,C.red);
  box(slide,ctx,"真实链路约束：GPU、网络或模型服务不可用时，系统必须暴露失败而不是生成替代结果。",860,210,350,126,C.white,C.gold);
  metric(slide,ctx,"安全前置","先门控，再生成",150,410,250,C.red);
  metric(slide,ctx,"证据约束","RAG 不是装饰",515,410,250,C.blue);
  metric(slide,ctx,"真实性","fail-closed",880,410,250,C.green);
  footer(slide,ctx);
  return slide;
}
''',
    "slide-03.mjs": r'''
import { C, slideBg, kicker, title, footer, pill, line } from "./theme.mjs";
export async function slide03(presentation, ctx) {
  const slide = presentation.slides.add();
  slideBg(slide, ctx);
  kicker(slide,ctx,"ARCHITECTURE");
  title(slide,ctx,"主链路是安全级联，不是裸模型链","每个模块都有可演示输出和实验记录。");
  const stages=[
    ["Voice / Text","输入与转写"],
    ["Normalize","术语保留"],
    ["Safety Gate","越界拒答"],
    ["RAG","证据检索"],
    ["LLM","回答生成"],
    ["Playback","句级播报"],
    ["Logging","指标记录"],
  ];
  let x=54;
  stages.forEach((s,i)=>{
    const fill=i===2?C.softRed:i===3?C.softBlue:i===6?C.softGreen:C.white;
    const accent=i===2?C.red:i===3?C.blue:i===6?C.green:C.cyan;
    ctx.addShape(slide,{x,y:250,w:146,h:104,fill,line:ctx.line("#D7E0EA",1)});
    ctx.addShape(slide,{x,y:250,w:146,h:6,fill:accent,line:ctx.line(accent,0)});
    ctx.addText(slide,{text:s[0],x:x+12,y:276,w:122,h:28,fontSize:18,bold:true,color:C.ink,align:"center"});
    ctx.addText(slide,{text:s[1],x:x+12,y:312,w:122,h:24,fontSize:15,color:C.muted,align:"center"});
    if(i<stages.length-1){ line(slide,ctx,x+154,300,36,3,C.line); ctx.addText(slide,{text:"→",x:x+183,y:284,w:28,h:28,fontSize:26,color:C.muted}); }
    x+=174;
  });
  pill(slide,ctx,"原则 1：危险请求在模型前拦截",116,438,290,C.softRed,C.red);
  pill(slide,ctx,"原则 2：领域回答必须带证据",496,438,290,C.softBlue,C.blue);
  pill(slide,ctx,"原则 3：答辩现场可无 GPU 运行",876,438,290,C.softGreen,C.green);
  footer(slide,ctx);
  return slide;
}
''',
    "slide-04.mjs": r'''
import { C, slideBg, kicker, title, footer, metric, box } from "./theme.mjs";
export async function slide04(presentation, ctx) {
  const slide = presentation.slides.add();
  slideBg(slide, ctx);
  kicker(slide,ctx,"RAG EVIDENCE");
  title(slide,ctx,"知识库让回答可解释，检索评测让结果可量化","ShipVoice 不是凭空生成安全建议。");
  metric(slide,ctx,"20","船厂安全知识条目",76,214,230,C.blue);
  metric(slide,ctx,"5/5","代表问题 hit@1",336,214,230,C.green);
  metric(slide,ctx,"5/5","代表问题 hit@3",596,214,230,C.green);
  metric(slide,ctx,"3","每次回答展示证据",856,214,230,C.gold);
  box(slide,ctx,"覆盖主题：密闭舱室、动火、高处焊接、船体分段吊装、舾装管路试压、压载水舱检修、PPE、应急处置、术语识别。",90,392,480,116,C.white,C.blue);
  box(slide,ctx,"证据展示：每次回答显示 top-k 知识条目、检索分数和门控标签，便于老师现场追问时解释系统行为。",640,392,480,116,C.white,C.green);
  footer(slide,ctx);
  return slide;
}
''',
    "slide-05.mjs": r'''
import { C, slideBg, kicker, title, footer, box, pill } from "./theme.mjs";
export async function slide05(presentation, ctx) {
  const slide = presentation.slides.add();
  slideBg(slide, ctx);
  kicker(slide,ctx,"SAFETY GATE");
  title(slide,ctx,"安全门控把高风险输入挡在生成之前","55 条 benchmark 验证离题、违规绕行、提示注入和边界应急。");
  const rows=[
    ["off-domain","股票投资等非船厂安全问题","短路拒答",C.gold],
    ["unsafe request","绕过检查、跳过审批、破坏流程","拒绝并重申规范",C.red],
    ["prompt injection","要求忽略安全规则或规避审批","不服从恶意指令",C.red],
    ["domain-safe","密闭舱室、动火、吊装、试压等","进入 RAG + 生成",C.green],
  ];
  rows.forEach((r,i)=>{
    const y=206+i*86;
    pill(slide,ctx,r[0],80,y,160,i<1?C.softGold:i<3?C.softRed:C.softGreen,r[3]);
    ctx.addText(slide,{text:r[1],x:278,y:y+4,w:430,h:28,fontSize:20,bold:true,color:C.ink});
    ctx.addText(slide,{text:r[2],x:760,y:y+4,w:300,h:28,fontSize:20,color:r[3],bold:true});
    ctx.addShape(slide,{x:74,y:y+50,w:1048,h:1,fill:"#DDE5F0",line:ctx.line("#DDE5F0",0)});
  });
  box(slide,ctx,"当前完整 pipeline 安全评测：标签准确率 100.0%，allow/block 决策准确率 100.0%，危险请求误放行 0。LoRA 不能绕过门控。",120,580,1000,58,C.white,C.red);
  footer(slide,ctx);
  return slide;
}
''',
    "slide-06.mjs": r'''
import { C, slideBg, kicker, title, footer } from "./theme.mjs";
export async function slide06(presentation, ctx) {
  const slide = presentation.slides.add();
  slideBg(slide, ctx);
  kicker(slide,ctx,"DEMO");
  title(slide,ctx,"本地演示面板展示完整决策过程","无 GPU 时也可以跑通输入、门控、证据、回答和指标。");
  await ctx.addImage(slide,{path:`${ctx.assetDir}/demo_panel_safety.png`,x:70,y:190,w:540,h:330,fit:"contain",alt:"ShipVoice safety demo panel"});
  await ctx.addImage(slide,{path:`${ctx.assetDir}/demo_panel_backend.png`,x:680,y:190,w:520,h:330,fit:"contain",alt:"ShipVoice backend metrics panel"});
  ctx.addText(slide,{text:"演示问题覆盖：安全作业、领域术语、off-domain、危险请求、prompt injection。",x:86,y:548,w:1030,h:30,fontSize:20,bold:true,color:C.ink,align:"center"});
  footer(slide,ctx);
  return slide;
}
''',
    "slide-07.mjs": r'''
import { C, slideBg, kicker, title, footer, metric, box } from "./theme.mjs";
export async function slide07(presentation, ctx) {
  const slide = presentation.slides.add();
  slideBg(slide, ctx);
  kicker(slide,ctx,"FINE-TUNING");
  title(slide,ctx,"LoRA/QLoRA 是超出要求的领域适配实验","我们跑了真实远端 GPU 训练，而不是只写计划。");
  metric(slide,ctx,"Qwen2.5-7B","Base model",78,212,300,C.blue);
  metric(slide,ctx,"RTX 4090","24GB GPU",438,212,230,C.cyan);
  metric(slide,ctx,"1000","SFT train",728,212,190,C.green);
  metric(slide,ctx,"250","optimizer steps",978,212,190,C.gold);
  box(slide,ctx,"训练配置：4-bit LoRA/QLoRA，target modules 覆盖 attention 与 MLP 投影层，2 epochs，最终 train_loss = 0.1677。",104,384,470,116,C.white,C.blue);
  box(slide,ctx,"产物证据：150 条 holdout 对比、adapter_model.safetensors 约 154MB，base/LoRA JSONL、训练日志与 artifact manifest 均已拉回本地。",644,384,470,116,C.white,C.green);
  footer(slide,ctx);
  return slide;
}
''',
    "slide-08.mjs": r'''
import { C, slideBg, kicker, title, footer, box } from "./theme.mjs";
export async function slide08(presentation, ctx) {
  const slide = presentation.slides.add();
  slideBg(slide, ctx);
  kicker(slide,ctx,"EVALUATION");
  title(slide,ctx,"Base 与 LoRA 对比：微调用于增强，不替代门控","实验结果支持安全架构，而不是盲目吹微调。");
  const max=220;
  const base=211.2, lora=161.2;
  ctx.addText(slide,{text:"平均回答长度",x:120,y:226,w:220,h:28,fontSize:22,bold:true,color:C.ink});
  ctx.addShape(slide,{x:120,y:286,w:base/max*720,h:42,fill:C.blue,line:ctx.line(C.blue,0)});
  ctx.addText(slide,{text:"Base 211.2 chars",x:120+base/max*720+18,y:292,w:240,h:28,fontSize:19,color:C.ink});
  ctx.addShape(slide,{x:120,y:366,w:lora/max*720,h:42,fill:C.green,line:ctx.line(C.green,0)});
  ctx.addText(slide,{text:"LoRA 161.2 chars",x:120+lora/max*720+18,y:372,w:240,h:28,fontSize:19,color:C.ink});
  box(slide,ctx,"Base：150 条 holdout 中更像通用助手，off-domain 拒答 1/10。",110,484,330,90,C.white,C.blue);
  box(slide,ctx,"LoRA：安全类拒答从 12 提升到 38，off-domain 拒答达到 10/10。",474,484,330,90,C.white,C.green);
  box(slide,ctx,"限制：LoRA 仍不能裸用，正式链路必须先过安全门控和 RAG。",838,484,330,90,C.white,C.red);
  footer(slide,ctx);
  return slide;
}
''',
    "slide-09.mjs": r'''
import { C, slideBg, kicker, title, footer, box, pill } from "./theme.mjs";
export async function slide09(presentation, ctx) {
  const slide = presentation.slides.add();
  slideBg(slide, ctx);
  kicker(slide,ctx,"REPRODUCIBILITY");
  title(slide,ctx,"交付物不是截图工程：代码、日志、adapter、评测都可追溯","老师可以从 README 跑到验证脚本。");
  const cmds=[
    ["本地验证","python scripts\\\\validate_project.py --quick"],
    ["本地应用","python run_app.py --env-file configs/runtime.real.env --port 8026"],
    ["安全评测","python scripts\\\\evaluate_safety_gate.py --fail-on-critical"],
    ["远端训练","remote/train_qwen_lora.py"],
    ["远端评测","remote/evaluate_qwen_lora.py"],
  ];
  cmds.forEach((c,i)=>{
    const y=176+i*72;
    pill(slide,ctx,c[0],88,y,150,i<2?C.softBlue:C.softGreen,i<2?C.blue:C.green);
    ctx.addText(slide,{text:c[1],x:278,y:y+4,w:800,h:32,fontSize:22,color:C.ink,typeface:ctx.fonts.mono});
  });
  box(slide,ctx,"核心证据目录：results/remote_autodl_20260621_expanded，包括训练日志、base/LoRA JSONL、adapter、结果摘要和远端状态。",138,560,960,58,C.white,C.gold);
  footer(slide,ctx);
  return slide;
}
''',
    "slide-10.mjs": r'''
import { C, slideBg, kicker, title, footer, box } from "./theme.mjs";
export async function slide10(presentation, ctx) {
  const slide = presentation.slides.add();
  slideBg(slide, ctx, C.navy);
  kicker(slide,ctx,"CONCLUSION",64,48,C.cyan);
  title(slide,ctx,"最高价值：安全关键领域的可控语音问答系统","微调是加分项，安全架构才是核心竞争力。",true);
  ctx.addShape(slide,{x:92,y:238,w:500,h:118,fill:"#12345A",line:ctx.line("#4B6F98",1)});
  ctx.addShape(slide,{x:92,y:238,w:5,h:118,fill:C.green,line:ctx.line(C.green,0)});
  ctx.addText(slide,{text:"已经完成：可运行 demo、RAG、安全门控、benchmark、AutoDL 远端微调、base-vs-LoRA 对比、报告初稿。",x:112,y:260,w:462,h:76,fontSize:19,color:"#DDEBFF",valign:"mid"});
  ctx.addShape(slide,{x:682,y:238,w:500,h:118,fill:"#12345A",line:ctx.line("#4B6F98",1)});
  ctx.addShape(slide,{x:682,y:238,w:5,h:118,fill:C.gold,line:ctx.line(C.gold,0)});
  ctx.addText(slide,{text:"后续补强：组员姓名学号、真实语音样例、答辩视频和最终提交包清理。",x:702,y:260,w:462,h:76,fontSize:19,color:"#DDEBFF",valign:"mid"});
  ctx.addText(slide,{text:"答辩收束句：我们不是把模型串起来，而是把安全边界、领域证据和实验闭环放进了语音问答系统。",x:100,y:456,w:1080,h:72,fontSize:30,bold:true,color:C.white,align:"center",typeface:ctx.fonts.title});
  ctx.addText(slide,{text:"姓名 / 学号待补充",x:100,y:614,w:1080,h:30,fontSize:20,color:"#B7C9E8",align:"center"});
  return slide;
}
''',
}


def write_workspace() -> None:
    SLIDES_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    LAYOUT_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    (SLIDES_DIR / "theme.mjs").write_text(THEME, encoding="utf-8")
    for name, content in SLIDES.items():
        (SLIDES_DIR / name).write_text(content.strip() + "\n", encoding="utf-8")

    for name in ["demo_panel_safety.png", "demo_panel_backend.png"]:
        src = ROOT / "results" / name
        if src.exists():
            shutil.copy2(src, ASSET_DIR / name)

    (WORKSPACE / "profile-plan.txt").write_text(
        "\n".join(
            [
                "task mode: create",
                "primary deck-profile: engineering-platform",
                "required proof objects: architecture flow, safety gate matrix, RAG metrics, LoRA training metrics, base-vs-LoRA comparison",
                "asset requirements: local demo screenshots only, no fabricated logos",
                "QA gates: 10 slides, varied layouts, no unsupported model claims, readable technical labels",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (WORKSPACE / "claim-spine.txt").write_text(
        "\n".join(
            [
                "Thesis: ShipVoice is a safe-by-design voice QA assistant for shipyard safety, not a naive ASR-LLM-TTS chain.",
                "Audience: course instructor and classmates.",
                "Arc: risk -> architecture -> evidence -> fine-tuning -> conclusion.",
                "1 Cover: proof metrics.",
                "2 Problem: safety-critical voice QA needs controls.",
                "3 Architecture: gate and RAG before generation.",
                "4 RAG: knowledge base and hit-rate.",
                "5 Safety gate: refusal boundary.",
                "6 Demo: runnable local panel.",
                "7 Fine-tuning: real Qwen LoRA run and online serving path.",
                "8 Evaluation: base vs LoRA tradeoff.",
                "9 Reproducibility: commands and artifacts.",
                "10 Conclusion: safety architecture is the core claim.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "workspace": str(WORKSPACE),
        "slides_dir": str(SLIDES_DIR),
        "preview_dir": str(PREVIEW_DIR),
        "layout_dir": str(LAYOUT_DIR),
        "asset_dir": str(ASSET_DIR),
        "final_pptx": str(FINAL_PPTX),
        "slide_count": len(SLIDES),
    }
    (WORKSPACE / "deck_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    write_workspace()
