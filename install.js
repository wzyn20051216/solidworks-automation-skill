#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const os = require('os');

const SKILL_NAME = 'solidworks-automation';
const REPO_URL = 'https://github.com/wzyn20051216/solidworks-automation-skill.git';

function shellQuote(value) {
  return `"${String(value).replace(/"/g, '\\"')}"`;
}

// 检测所有存在的 skills 目录
function getAllSkillsDirs() {
  const homeDir = os.homedir();
  const possibleDirs = [
    path.join(homeDir, '.agents', 'skills'),
    path.join(homeDir, '.claude', 'skills'),
    path.join(homeDir, '.codex', 'skills'),
    path.join(homeDir, '.cursor', 'skills'),
    path.join(homeDir, '.openclaw', 'skills'),
  ];

  const existingDirs = possibleDirs.filter(dir => fs.existsSync(dir));

  // 如果没有找到任何目录,创建对 OpenClaw / Codex 更友好的默认目录
  if (existingDirs.length === 0) {
    const bootstrapDirs = [
      path.join(homeDir, '.codex', 'skills'),
      path.join(homeDir, '.openclaw', 'skills'),
    ];

    bootstrapDirs.forEach(dir => fs.mkdirSync(dir, { recursive: true }));
    return bootstrapDirs;
  }

  return existingDirs;
}

// 在单个目录中安装或更新
function installToDir(skillsDir) {
  const targetDir = path.join(skillsDir, SKILL_NAME);

  console.log(`\n📁 目标目录: ${targetDir}`);

  // 检查是否已安装
  if (fs.existsSync(targetDir)) {
    console.log('⚠️  Skill 已存在，正在更新...');
    try {
      execSync('git pull', { cwd: targetDir, stdio: 'inherit' });
      console.log('✅ 更新成功！');
      return true;
    } catch (error) {
      console.log('⚠️  更新失败，尝试重新安装...');
      fs.rmSync(targetDir, { recursive: true, force: true });
    }
  }

  // 克隆仓库
  try {
    console.log('📦 正在下载...');
    execSync(`git clone ${REPO_URL} "${targetDir}"`, { stdio: 'inherit' });
    console.log('✅ 安装成功！');
  return true;
  } catch (error) {
    console.error(`❌ 安装失败: ${error.message}`);
    return false;
  }
}

function selectPrimaryInstallDir(installedDirs) {
  const priority = [
    path.join('.codex', 'skills'),
    path.join('.claude', 'skills'),
    path.join('.agents', 'skills'),
    path.join('.openclaw', 'skills'),
    path.join('.cursor', 'skills'),
  ];

  for (const marker of priority) {
    const found = installedDirs.find(dir => dir.includes(marker));
    if (found) {
      return found;
    }
  }

  return installedDirs[0];
}

function registerMcpForAiClients(installedDirs) {
  if (installedDirs.length === 0) {
    return;
  }

  const primaryDir = selectPrimaryInstallDir(installedDirs);
  const registerScript = path.join(primaryDir, 'mcp-server', 'register_all_ai_mcp.js');

  if (!fs.existsSync(registerScript)) {
    console.log(`⚠️  未找到 MCP 注册脚本: ${registerScript}`);
    return;
  }

  console.log('\n🔌 正在自动注册 MCP 到常见 AI 客户端...');
  try {
    execSync(`node ${shellQuote(registerScript)} --install-dependencies`, { stdio: 'inherit' });
  } catch (error) {
    console.log('⚠️  MCP 自动注册未完全成功，可稍后手动执行:');
    console.log(`  node ${shellQuote(registerScript)} --install-dependencies`);
  }
}

function install() {
  console.log('🚀 安装 SolidWorks Automation Skill...\n');

  const skillsDirs = getAllSkillsDirs();
  console.log(`检测到 ${skillsDirs.length} 个 AI 工具目录:\n${skillsDirs.map(d => `  - ${d}`).join('\n')}\n`);

  let successCount = 0;
  const installedDirs = [];
  for (const dir of skillsDirs) {
    if (installToDir(dir)) {
      successCount++;
      installedDirs.push(path.join(dir, SKILL_NAME));
    }
  }

  // 安装 Python 依赖(只需要安装一次)
  if (successCount > 0) {
    console.log('\n📦 安装 Python 基础依赖...');
    try {
      execSync('pip install "pywin32>=305" "comtypes>=1.2.0"', { stdio: 'inherit' });
    } catch (error) {
      console.log('⚠️  请手动安装依赖: pip install "pywin32>=305" "comtypes>=1.2.0"');
    }

    registerMcpForAiClients(installedDirs);

    console.log(`\n✅ 成功安装到 ${successCount}/${skillsDirs.length} 个目录！`);
    console.log('\n使用方法:');
    console.log('  在 Claude/Codex/Cursor/OpenClaw 中提到 SolidWorks、OpenClaw、龙虾、CAD、3D建模等关键词');
    console.log('  AI 会自动调用此 skill\n');

    const primaryDir = selectPrimaryInstallDir(installedDirs);
    const registerAllScript = path.join(primaryDir, 'mcp-server', 'register_all_ai_mcp.ps1');
    console.log('如需重新修复/覆盖 MCP 配置，可执行:');
    console.log(`  powershell -ExecutionPolicy Bypass -File "${registerAllScript}" -InstallDependencies\n`);
  } else {
    console.error('\n❌ 所有目录安装均失败');
    process.exit(1);
  }
}

install();
