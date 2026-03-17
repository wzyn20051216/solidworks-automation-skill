#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const os = require('os');

const SKILL_NAME = 'solidworks-automation';
const REPO_URL = 'https://github.com/wzyn20051216/solidworks-automation-skill.git';

// 检测所有存在的 skills 目录
function getAllSkillsDirs() {
  const homeDir = os.homedir();
  const possibleDirs = [
    path.join(homeDir, '.claude', 'skills'),
    path.join(homeDir, '.codex', 'skills'),
    path.join(homeDir, '.cursor', 'skills'),
  ];

  const existingDirs = possibleDirs.filter(dir => fs.existsSync(dir));

  // 如果没有找到任何目录,创建 Claude 默认目录
  if (existingDirs.length === 0) {
    const claudeDir = path.join(homeDir, '.claude', 'skills');
    fs.mkdirSync(claudeDir, { recursive: true });
    return [claudeDir];
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

function install() {
  console.log('🚀 安装 SolidWorks Automation Skill...\n');

  const skillsDirs = getAllSkillsDirs();
  console.log(`检测到 ${skillsDirs.length} 个 AI 工具目录:\n${skillsDirs.map(d => `  - ${d}`).join('\n')}\n`);

  let successCount = 0;
  for (const dir of skillsDirs) {
    if (installToDir(dir)) {
      successCount++;
    }
  }

  // 安装 Python 依赖(只需要安装一次)
  if (successCount > 0) {
    console.log('\n📦 安装 Python 依赖...');
    try {
      execSync('pip install pywin32>=305', { stdio: 'inherit' });
    } catch (error) {
      console.log('⚠️  请手动安装依赖: pip install pywin32');
    }

    console.log(`\n✅ 成功安装到 ${successCount}/${skillsDirs.length} 个目录！`);
    console.log('\n使用方法:');
    console.log('  在 Claude/Codex/Cursor 中提到 SolidWorks、CAD、3D建模等关键词');
    console.log('  AI 会自动调用此 skill\n');
  } else {
    console.error('\n❌ 所有目录安装均失败');
    process.exit(1);
  }
}

install();
