import { FilePlus } from "@phosphor-icons/react";
import type { AgentConversation, AgentProviderId } from "../types";

type Option = { value: string; label: string; disabled?: boolean };
type ConversationControlsProps = {
  conversations: AgentConversation[];
  activeConversationId?: string;
  provider: AgentProviderId;
  model: string;
  providers: Option[];
  models: Option[];
  onSelectConversation: (id: string) => void;
  onCreateConversation: () => void;
  onSelectProvider: (id: AgentProviderId) => void;
  onSelectModel: (model: string) => void;
};

/** @brief 项目内独立对话、AI 公司和模型的统一切换控件。 */
export function ConversationControls({
  conversations,
  activeConversationId,
  provider,
  model,
  providers,
  models,
  onSelectConversation,
  onCreateConversation,
  onSelectProvider,
  onSelectModel,
}: ConversationControlsProps) {
  return (
    <div className="agent-conversation-controls">
      <select aria-label="切换 AI 对话" value={activeConversationId ?? ""} onChange={(event) => onSelectConversation(event.target.value)}>
        {conversations.length === 0 ? <option value="">当前项目暂无对话</option> : null}
        {conversations.map((conversation) => <option value={conversation.id} key={conversation.id}>{conversation.title}</option>)}
      </select>
      <button type="button" aria-label="新建 AI 对话" title="新建 AI 对话" onClick={onCreateConversation}>
        <FilePlus size={15} weight="bold" />
      </button>
      <select aria-label="选择 AI 公司" value={provider} onChange={(event) => onSelectProvider(event.target.value as AgentProviderId)}>
        {providers.map((option) => <option value={option.value} disabled={option.disabled} key={option.value}>{option.label}</option>)}
      </select>
      <select aria-label="选择对话模型" value={model} onChange={(event) => onSelectModel(event.target.value)}>
        {models.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}
      </select>
    </div>
  );
}
