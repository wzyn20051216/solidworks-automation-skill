import {
  Archive,
  ArrowCounterClockwise,
  CaretDown,
  Check,
  Copy,
  FilePlus,
  FolderOpen,
  MagnifyingGlass,
  PencilSimple,
  SpinnerGap,
  Trash,
} from "@phosphor-icons/react";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import { filterProjects } from "../domain/projects";
import type { ProjectRecord } from "../types";

type ProjectSwitcherProps = {
  activeProjectId: string;
  projectName: string;
  projectNameDraft: string;
  projects: ProjectRecord[];
  projectTaskCounts: Record<string, number>;
  editing: boolean;
  menuOpen: boolean;
  reducedMotion: boolean;
  deleteCandidateProjectId: string | null;
  deletingProjectId: string | null;
  onDraftChange: (value: string) => void;
  onCommitName: () => void;
  onCancelEdit: () => void;
  onStartEdit: () => void;
  onToggleMenu: () => void;
  onSelect: (project: ProjectRecord) => void;
  onCreate: () => void;
  onDuplicate: (project: ProjectRecord) => void;
  onToggleArchive: (project: ProjectRecord) => void;
  onDelete: (project: ProjectRecord) => void;
};

/** @brief ChatGPT 风格的项目选择、搜索和项目元数据管理入口。 */
export function ProjectSwitcher({
  activeProjectId,
  projectName,
  projectNameDraft,
  projects,
  projectTaskCounts,
  editing,
  menuOpen,
  reducedMotion,
  deleteCandidateProjectId,
  deletingProjectId,
  onDraftChange,
  onCommitName,
  onCancelEdit,
  onStartEdit,
  onToggleMenu,
  onSelect,
  onCreate,
  onDuplicate,
  onToggleArchive,
  onDelete,
}: ProjectSwitcherProps) {
  const [query, setQuery] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const visibleProjects = useMemo(
    () => filterProjects(projects, query, showArchived),
    [projects, query, showArchived],
  );
  const archivedCount = projects.filter((project) => project.archivedAt).length;
  const activeCount = projects.length - archivedCount;

  return (
    <div className="project-switcher">
      <div className="project-name-row">
        {editing ? (
          <input
            autoFocus
            value={projectNameDraft}
            maxLength={48}
            aria-label="项目名称"
            onChange={(event) => onDraftChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") onCommitName();
              if (event.key === "Escape") onCancelEdit();
            }}
          />
        ) : (
          <button
            className="project-switcher-trigger"
            type="button"
            aria-label={`切换项目，当前为 ${projectName}`}
            aria-expanded={menuOpen}
            onClick={onToggleMenu}
          >
            <FolderOpen size={15} weight="duotone" />
            <strong title={projectName}>{projectName}</strong>
            <CaretDown size={14} weight="bold" />
          </button>
        )}
        <button
          className="project-name-action"
          type="button"
          aria-label={editing ? "确认项目名称" : "修改项目名称"}
          title={editing ? "确认项目名称" : "修改项目名称"}
          onClick={editing ? onCommitName : onStartEdit}
        >
          {editing ? <Check size={15} weight="bold" /> : <PencilSimple size={15} weight="duotone" />}
        </button>
      </div>
      <AnimatePresence>
        {menuOpen && !editing ? (
          <motion.div
            className="project-switcher-menu"
            role="menu"
            initial={reducedMotion ? false : { opacity: 0, y: -5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reducedMotion ? undefined : { opacity: 0, y: -5 }}
            transition={{ duration: 0.16 }}
          >
            <div className="project-switcher-tabs" role="tablist" aria-label="项目范围">
              <button type="button" role="tab" aria-selected={!showArchived} onClick={() => setShowArchived(false)}>
                项目 {activeCount}
              </button>
              <button type="button" role="tab" aria-selected={showArchived} onClick={() => setShowArchived(true)}>
                归档 {archivedCount}
              </button>
            </div>
            <label className="project-search">
              <MagnifyingGlass size={14} />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索项目或目录" />
            </label>
            <div className="project-switcher-list">
              {visibleProjects.map((project) => {
                const taskCount = projectTaskCounts[project.id] ?? 0;
                return (
                  <div className={project.id === activeProjectId ? "project-switcher-option active" : "project-switcher-option"} key={project.id}>
                    <button className="project-switcher-select" type="button" role="menuitem" onClick={() => onSelect(project)}>
                      <FolderOpen size={15} weight="duotone" />
                      <span>
                        <strong>{project.name}</strong>
                        <small>{taskCount ? `${taskCount} 条任务` : "空项目"}</small>
                      </span>
                      {project.id === activeProjectId ? <Check size={14} weight="bold" /> : null}
                    </button>
                    <div className="project-option-actions">
                      {!project.archivedAt ? (
                        <button type="button" aria-label={`复制项目 ${project.name}`} title="复制项目结构" onClick={() => onDuplicate(project)}>
                          <Copy size={14} />
                        </button>
                      ) : null}
                      <button
                        type="button"
                        disabled={project.id === activeProjectId}
                        aria-label={`${project.archivedAt ? "恢复" : "归档"}项目 ${project.name}`}
                        title={project.id === activeProjectId ? "当前项目不能归档" : project.archivedAt ? "恢复项目" : "归档项目"}
                        onClick={() => onToggleArchive(project)}
                      >
                        {project.archivedAt ? <ArrowCounterClockwise size={14} /> : <Archive size={14} />}
                      </button>
                      <button
                        className={deleteCandidateProjectId === project.id ? "project-delete-button confirm" : "project-delete-button"}
                        type="button"
                        disabled={(!project.archivedAt && activeCount <= 1) || deletingProjectId !== null}
                        aria-label={deleteCandidateProjectId === project.id ? `确认删除项目 ${project.name}` : `删除项目 ${project.name}`}
                        title={!project.archivedAt && activeCount <= 1 ? "至少保留一个未归档项目" : deleteCandidateProjectId === project.id ? "再次点击确认删除项目" : "删除项目"}
                        onClick={() => onDelete(project)}
                      >
                        {deletingProjectId === project.id ? <SpinnerGap className="spin" size={14} /> : deleteCandidateProjectId === project.id ? <Check size={14} weight="bold" /> : <Trash size={14} weight="duotone" />}
                      </button>
                    </div>
                  </div>
                );
              })}
              {!visibleProjects.length ? <div className="project-search-empty">没有匹配的{showArchived ? "归档" : "项目"}</div> : null}
            </div>
            <button className="create-project-button" type="button" role="menuitem" onClick={onCreate}>
              <FilePlus size={15} weight="bold" />
              新建项目
            </button>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
