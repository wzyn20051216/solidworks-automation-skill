#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const os = require('os');

const SKILL_NAME = 'solidworks-automation';
const REPO_URL = 'https://github.com/wzyn20051216/solidworks-automation-skill.git';

// 检测 skills 目录
function getSkillsDir() {
  const homeDir = os.homedir();
  const possibleDirs = [
    path.join(homeDir, '.claude', 'skills'),
    path.join(homeDir, '.codex', 'skills'),
    path.join(homeDir, '.cursor', 'skills'),
  ];

  for (const dir of possibleDirs) {
    if (fs.existsSync(dir)) {
      return dir;
    }
  }

  // 默认使用 Claude
  const claudeDir = path.join(homeDir, '.claude', 'skills');
  fs.mkdirSync(claudeDir, { recursive: true });
  return claudeDir;
}

function install() {
  console.log('🚀 安装 SolidWorks Automation Skill...\n');

  const skillsDir = getSkillsDir();
  const targetDir = path.join(skillsDir, SKILL_NAME);

  console.log(`📁 目标目录: ${targetDir}`);

  // 检查是否已安装
  if (fs.existsSync(targetDir)) {
    console.log('⚠️  Skill 已存在，正在更新...');
    try {
      execSync('git pull', { cwd: targetDir, stdio: 'inherit' });
      console.log('\n✅ 更新成功！');
      return;
    } catch (error) {
      console.log('⚠️  更新失败，尝试重新安装...');
      fs.rmSync(targetDir, { recursive: true, force: true });
    }
  }

  // 克隆仓库
  try {
    console.log('\n📦 正在下载...');
    execSync(`git clone ${REPO_URL} "${targetDir}"`, { stdio: 'inherit' });

    // 安装 Python 依赖
    console.log('\n📦 安装 Python 依赖...');
    try {
      execSync('pip install pywin32>=305', { stdio: 'inherit' });
    } catch (error) {
      console.log('⚠️  请手动安装依赖: pip install pywin32');
    }

    console.log('\n✅ 安装成功！');
    console.log('\n使用方法:');
    console.log('  在 Claude 中提到 SolidWorks、CAD、3D建模等关键词');
    console.log('  Claude 会自动调用此 skill\n');
  } catch (error) {
    console.error('❌ 安装失败:', error.message);
    process.exit(1);
  }
}

install();
