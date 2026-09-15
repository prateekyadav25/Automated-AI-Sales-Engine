/* Generated from FastAPI OpenAPI. Do not edit by hand. */
export type GeneratedPaths = {
  "/api/v1/accounts": "get, post";
  "/api/v1/accounts/{account_id}": "get, patch";
  "/api/v1/accounts/{account_id}/context": "get";
  "/api/v1/acquisition/capture": "post";
  "/api/v1/acquisition/captures": "get";
  "/api/v1/acquisition/dedupe": "get";
  "/api/v1/acquisition/dedupe/{review_id}/decide": "post";
  "/api/v1/acquisition/form-keys": "get, post";
  "/api/v1/acquisition/form-keys/{key_id}/revoke": "post";
  "/api/v1/acquisition/overview": "get";
  "/api/v1/activities": "get";
  "/api/v1/admin/audit": "get";
  "/api/v1/admin/flags": "get";
  "/api/v1/admin/flags/{flag_id}": "patch";
  "/api/v1/admin/role-assignments": "get";
  "/api/v1/admin/roles": "get";
  "/api/v1/admin/teams": "get, post";
  "/api/v1/admin/territories": "get, post";
  "/api/v1/admin/users": "get";
  "/api/v1/ai/approvals": "get";
  "/api/v1/ai/approvals/{approval_id}/decide": "post";
  "/api/v1/ai/copilot/chat": "post";
  "/api/v1/ai/drafts/email": "post";
  "/api/v1/ai/knowledge": "get, post";
  "/api/v1/ai/knowledge/search": "get";
  "/api/v1/ai/knowledge/{source_id}/file": "get";
  "/api/v1/ai/meeting-prep/accounts/{account_id}": "post";
  "/api/v1/ai/research/accounts/{account_id}": "post";
  "/api/v1/ai/summaries/{entity_type}/{entity_id}": "post";
  "/api/v1/auth/login": "post";
  "/api/v1/auth/logout": "post";
  "/api/v1/auth/me": "get";
  "/api/v1/auth/refresh": "post";
  "/api/v1/auth/sessions": "get";
  "/api/v1/auth/sessions/revoke-all": "post";
  "/api/v1/auth/sessions/{family_id}/revoke": "post";
  "/api/v1/autonomy/activity": "get";
  "/api/v1/autonomy/entities/{entity_type}/{entity_id}": "get";
  "/api/v1/autonomy/entities/{entity_type}/{entity_id}/trace": "get";
  "/api/v1/autonomy/events": "get";
  "/api/v1/autonomy/pause": "post";
  "/api/v1/autonomy/resume": "post";
  "/api/v1/autonomy/retry": "post";
  "/api/v1/autonomy/runs": "get, post";
  "/api/v1/autonomy/runs/{run_id}": "get";
  "/api/v1/autonomy/settings": "get, patch";
  "/api/v1/autonomy/status": "get";
  "/api/v1/command-center/activity": "get";
  "/api/v1/command-center/kpis": "get";
  "/api/v1/command-center/overview": "get";
  "/api/v1/command-center/pipeline-mix": "get";
  "/api/v1/command-center/work-queue": "get";
  "/api/v1/contacts": "get, post";
  "/api/v1/contacts/{contact_id}": "get, patch";
  "/api/v1/customers": "get";
  "/api/v1/customers/{customer_id}": "get";
  "/api/v1/customers/{customer_id}/churn": "post";
  "/api/v1/discovery/health": "get";
  "/api/v1/discovery/run": "post";
  "/api/v1/icps": "get, post";
  "/api/v1/icps/{icp_id}": "patch";
  "/api/v1/imports/commit": "post";
  "/api/v1/imports/preview": "post";
  "/api/v1/integrations": "get";
  "/api/v1/integrations/calendar/book": "post";
  "/api/v1/integrations/connectors": "get";
  "/api/v1/integrations/credentials": "post";
  "/api/v1/integrations/google/callback": "get";
  "/api/v1/integrations/google/connect": "get";
  "/api/v1/integrations/inbox/simulate": "post";
  "/api/v1/integrations/mappings": "get";
  "/api/v1/integrations/mappings/{mapping_id}": "patch";
  "/api/v1/integrations/mappings/{mapping_id}/confirm": "post";
  "/api/v1/integrations/mappings/{mapping_id}/ignore": "post";
  "/api/v1/integrations/mappings/{mapping_id}/unlink": "post";
  "/api/v1/integrations/product-usage/events/{routing_token}": "post";
  "/api/v1/integrations/providers": "get";
  "/api/v1/integrations/provision-defaults": "post";
  "/api/v1/integrations/{account_id}": "delete";
  "/api/v1/leads": "get, post";
  "/api/v1/leads/{lead_id}": "get, patch";
  "/api/v1/leads/{lead_id}/enrich": "post";
  "/api/v1/leads/{lead_id}/nba": "post";
  "/api/v1/leads/{lead_id}/score": "post";
  "/api/v1/lifecycle/abm": "get, post";
  "/api/v1/lifecycle/accounts/{account_id}": "get";
  "/api/v1/lifecycle/advocacy": "get, post";
  "/api/v1/lifecycle/advocacy/referrals": "post";
  "/api/v1/lifecycle/campaigns": "get, post";
  "/api/v1/lifecycle/campaigns/{campaign_id}": "get";
  "/api/v1/lifecycle/campaigns/{campaign_id}/audience": "post";
  "/api/v1/lifecycle/campaigns/{campaign_id}/creative": "post";
  "/api/v1/lifecycle/campaigns/{campaign_id}/launch": "post";
  "/api/v1/lifecycle/campaigns/{campaign_id}/members": "post";
  "/api/v1/lifecycle/campaigns/{campaign_id}/pause": "post";
  "/api/v1/lifecycle/campaigns/{campaign_id}/sync": "post";
  "/api/v1/lifecycle/captures/{capture_id}/refresh": "post";
  "/api/v1/lifecycle/conversations": "get, post";
  "/api/v1/lifecycle/conversations/dial": "post";
  "/api/v1/lifecycle/conversations/{conversation_id}": "get";
  "/api/v1/lifecycle/deals": "get";
  "/api/v1/lifecycle/deals/rescore": "post";
  "/api/v1/lifecycle/enrollments": "get";
  "/api/v1/lifecycle/expansion": "get";
  "/api/v1/lifecycle/expansion/refresh": "post";
  "/api/v1/lifecycle/forecast": "get";
  "/api/v1/lifecycle/forecast/refresh": "post";
  "/api/v1/lifecycle/meetings": "get, post";
  "/api/v1/lifecycle/meetings/extract": "post";
  "/api/v1/lifecycle/meetings/{meeting_id}/capture": "post";
  "/api/v1/lifecycle/meetings/{meeting_id}/consent": "post";
  "/api/v1/lifecycle/meetings/{meeting_id}/transcript": "post";
  "/api/v1/lifecycle/models": "get";
  "/api/v1/lifecycle/overview": "get";
  "/api/v1/lifecycle/playbooks": "get, post";
  "/api/v1/lifecycle/playbooks/runs": "get";
  "/api/v1/lifecycle/playbooks/{playbook_id}/run": "post";
  "/api/v1/lifecycle/products": "get, post";
  "/api/v1/lifecycle/quotes": "get, post";
  "/api/v1/lifecycle/quotes/{quote_id}": "get";
  "/api/v1/lifecycle/quotes/{quote_id}/lines": "post";
  "/api/v1/lifecycle/renewals": "get";
  "/api/v1/lifecycle/renewals/{renewal_id}/complete": "post";
  "/api/v1/lifecycle/sequences": "get, post";
  "/api/v1/lifecycle/sequences/{sequence_id}": "get";
  "/api/v1/lifecycle/sequences/{sequence_id}/enroll": "post";
  "/api/v1/lifecycle/success": "get";
  "/api/v1/lifecycle/success/health/rebuild": "post";
  "/api/v1/lifecycle/success/health/{customer_id}": "post";
  "/api/v1/lifecycle/voice-scripts": "get, post";
  "/api/v1/lifecycle/voice-scripts/{script_id}/publish/{version_id}": "post";
  "/api/v1/lifecycle/voice-scripts/{script_id}/versions": "post";
  "/api/v1/market": "get, post";
  "/api/v1/market/desk/signals": "get";
  "/api/v1/market/desk/triggers": "get";
  "/api/v1/market/overview": "get";
  "/api/v1/market/refresh": "post";
  "/api/v1/market/{market_id}": "get";
  "/api/v1/market/{market_id}/score": "post";
  "/api/v1/ml/datasets": "get, post";
  "/api/v1/ml/models": "get";
  "/api/v1/ml/models/rollback": "post";
  "/api/v1/ml/models/{model_id}/artifact": "get";
  "/api/v1/ml/models/{model_id}/promote": "post";
  "/api/v1/ml/predictions": "get";
  "/api/v1/ml/readiness": "get";
  "/api/v1/ml/train": "post";
  "/api/v1/opportunities": "get, post";
  "/api/v1/opportunities/{opportunity_id}": "get, patch";
  "/api/v1/opportunities/{opportunity_id}/close-lost": "post";
  "/api/v1/opportunities/{opportunity_id}/close-won": "post";
  "/api/v1/opportunities/{opportunity_id}/nba": "post";
  "/api/v1/pilot/activate": "post";
  "/api/v1/pilot/briefs": "get";
  "/api/v1/pilot/briefs/{kind}": "post";
  "/api/v1/pilot/config-export": "get";
  "/api/v1/pilot/costs": "get";
  "/api/v1/pilot/overrides": "post";
  "/api/v1/pilot/quality": "get";
  "/api/v1/pilot/readiness": "get";
  "/api/v1/pilot/roi": "get";
  "/api/v1/pilot/whatsapp/templates": "get, post";
  "/api/v1/post-sale/attention": "get";
  "/api/v1/post-sale/customers/{customer_id}": "get";
  "/api/v1/post-sale/expansion": "get";
  "/api/v1/post-sale/expansion/{recommendation_id}/feedback": "post";
  "/api/v1/post-sale/expansion/{recommendation_id}/outcome": "post";
  "/api/v1/post-sale/expansion/{recommendation_id}/useful": "post";
  "/api/v1/post-sale/lanes": "get";
  "/api/v1/post-sale/referrals/{referral_id}/ingest": "post";
  "/api/v1/providers/actions": "get";
  "/api/v1/providers/actions/{action_id}/cancel": "post";
  "/api/v1/providers/actions/{action_id}/retry": "post";
  "/api/v1/public/forms/{token}": "get";
  "/api/v1/public/forms/{token}/capture": "post";
  "/api/v1/search": "get";
  "/api/v1/tasks": "get, post";
  "/api/v1/tasks/{task_id}": "get, patch";
  "/api/v1/webhooks/{provider}/{routing_token}": "post";
  "/health": "get";
  "/health/live": "get";
  "/health/ready": "get";
  "/metrics": "get";
  "/ready": "get";
};

export const generatedPathCount = 184;
export const generatedSchemaNames = [
  "AbmIn",
  "AbmOut",
  "AccountContextOut",
  "AccountIn",
  "AccountLifecycleOut",
  "AccountOut",
  "AcquisitionOverview",
  "ActivityOut",
  "AdvocacyIn",
  "AdvocacyOut",
  "ApprovalDecision",
  "ApprovalOut",
  "AuditOut",
  "AutonomyActivityOut",
  "AutonomyPauseIn",
  "AutonomyRetryIn",
  "AutonomyRunIn",
  "AutonomyRunOut",
  "AutonomyStatusOut",
  "AutonomyStepOut",
  "AutonomyTodayOut",
  "AutopilotSettingsIn",
  "AutopilotSettingsOut",
  "Body_upload_knowledge_api_v1_ai_knowledge_post",
  "BriefOut",
  "CalendarBookIn",
  "CalendarBookOut",
  "CampaignDetail",
  "CampaignIn",
  "CampaignLaunchOut",
  "CampaignMemberIn",
  "CampaignMemberOut",
  "CampaignOut",
  "CaptureIn",
  "CaptureOut",
  "CaptureResult",
  "ChurnIn",
  "CloseLostIn",
  "ConnectorOut",
  "ContactIn",
  "ContactOut",
  "ContractLineOut",
  "ContractOut",
  "ConversationIn",
  "ConversationOut",
  "CopilotRequest",
  "CopilotResponse",
  "CredentialIn",
  "Customer360Out",
  "CustomerOut",
  "CustomerRiskOut",
  "DatasetBuildIn",
  "DatasetOut",
  "DealInsightOut",
  "DedupeDecision",
  "DedupeOut",
  "DiscoveryHealthOut",
  "DiscoveryRunIn",
  "DiscoveryRunOut",
  "EmailDraftRequest",
  "EmailDraftResponse",
  "EmailMessageOut",
  "EnrollIn",
  "EnrollmentOut",
  "EntityAutomationOut",
  "EntityMappingChangeIn",
  "EntityMappingOut",
  "Envelope_AbmOut_",
  "Envelope_AccountContextOut_",
  "Envelope_AccountLifecycleOut_",
  "Envelope_AccountOut_",
  "Envelope_AcquisitionOverview_",
  "Envelope_AdvocacyOut_",
  "Envelope_ApprovalOut_",
  "Envelope_AutonomyRunOut_",
  "Envelope_AutonomyStatusOut_",
  "Envelope_AutopilotSettingsOut_",
  "Envelope_BriefOut_",
  "Envelope_CalendarBookOut_",
  "Envelope_CampaignDetail_",
  "Envelope_CampaignLaunchOut_",
  "Envelope_CampaignMemberOut_",
  "Envelope_CampaignOut_",
  "Envelope_CaptureResult_",
  "Envelope_ContactOut_",
  "Envelope_ConversationOut_",
  "Envelope_CopilotResponse_",
  "Envelope_Customer360Out_",
  "Envelope_CustomerOut_",
  "Envelope_DatasetOut_",
  "Envelope_DedupeOut_",
  "Envelope_DiscoveryHealthOut_",
  "Envelope_DiscoveryRunOut_",
  "Envelope_EmailDraftResponse_",
  "Envelope_EnrollmentOut_",
  "Envelope_EntityAutomationOut_",
  "Envelope_EntityMappingOut_",
  "Envelope_ExpansionRecOut_",
  "Envelope_FlagOut_",
  "Envelope_ForecastOut_",
  "Envelope_GoogleConnectOut_",
  "Envelope_HealthOut_",
  "Envelope_HealthRebuildOut_",
  "Envelope_ICPOut_",
  "Envelope_ImportPreviewOut_",
  "Envelope_InboxSimulateOut_",
  "Envelope_IntegrationAccountOut_",
  "Envelope_KPIOut_",
  "Envelope_KnowledgeUploadResponse_",
  "Envelope_LeadOut_",
  "Envelope_LeadScoreOut_",
  "Envelope_LifecycleOverview_",
  "Envelope_LoginResponse_",
  "Envelope_MarketOut_",
  "Envelope_MarketOverview_",
  "Envelope_MeetingCaptureOut_",
  "Envelope_MeetingOut_",
  "Envelope_ModelVersionOut_",
  "Envelope_NBAOut_",
  "Envelope_OpportunityOut_",
  "Envelope_PilotActivateOut_",
  "Envelope_PilotReadinessOut_",
  "Envelope_PlaybookOut_",
  "Envelope_PostSaleAttentionOut_",
  "Envelope_ProductOut_",
  "Envelope_ProviderActionOut_",
  "Envelope_QuoteOut_",
  "Envelope_ReferralOut_",
  "Envelope_RefreshOut_",
  "Envelope_RenewalOut_",
  "Envelope_SearchOut_",
  "Envelope_SequenceDetail_",
  "Envelope_TaskOut_",
  "Envelope_TeamOut_",
  "Envelope_TerritoryOut_",
  "Envelope_VoiceDialOut_",
  "Envelope_VoiceScriptOut_",
  "Envelope_VoiceScriptVersionOut_",
  "Envelope_WhatsAppTemplateOut_",
  "Envelope_WorkflowRunOut_",
  "Envelope_dict_",
  "Envelope_dict_str__Union_list_TaskOut___list_OpportunityOut____",
  "Envelope_list_AbmOut__",
  "Envelope_list_AccountOut__",
  "Envelope_list_ActivityOut__",
  "Envelope_list_ApprovalOut__",
  "Envelope_list_AuditOut__",
  "Envelope_list_AutonomyActivityOut__",
  "Envelope_list_AutonomyRunOut__",
  "Envelope_list_BriefOut__",
  "Envelope_list_CampaignOut__",
  "Envelope_list_CaptureOut__",
  "Envelope_list_ConnectorOut__",
  "Envelope_list_ContactOut__",
  "Envelope_list_ConversationOut__",
  "Envelope_list_CustomerOut__",
  "Envelope_list_DatasetOut__",
  "Envelope_list_DealInsightOut__",
  "Envelope_list_DedupeOut__",
  "Envelope_list_EnrollmentOut__",
  "Envelope_list_EntityMappingOut__",
  "Envelope_list_ExpansionRecOut__",
  "Envelope_list_FlagOut__",
  "Envelope_list_ForecastOut__",
  "Envelope_list_ICPOut__",
  "Envelope_list_IntegrationAccountOut__",
  "Envelope_list_KnowledgeHit__",
  "Envelope_list_LeadOut__",
  "Envelope_list_LifecycleLaneOut__",
  "Envelope_list_MarketOut__",
  "Envelope_list_MeetingOut__",
  "Envelope_list_ModelCardOut__",
  "Envelope_list_ModelVersionOut__",
  "Envelope_list_OpportunityOut__",
  "Envelope_list_PlaybookOut__",
  "Envelope_list_PredictionOut__",
  "Envelope_list_ProductOut__",
  "Envelope_list_ProviderActionOut__",
  "Envelope_list_ProviderHealthOut__",
  "Envelope_list_QuoteOut__",
  "Envelope_list_ReadinessOut__",
  "Envelope_list_RenewalOut__",
  "Envelope_list_RoleOut__",
  "Envelope_list_SequenceOut__",
  "Envelope_list_SessionOut__",
  "Envelope_list_SignalOut__",
  "Envelope_list_StageMixOut__",
  "Envelope_list_SuccessRow__",
  "Envelope_list_TaskOut__",
  "Envelope_list_TeamOut__",
  "Envelope_list_TerritoryOut__",
  "Envelope_list_TriggerOut__",
  "Envelope_list_UserOut__",
  "Envelope_list_VoiceScriptOut__",
  "Envelope_list_WhatsAppTemplateOut__",
  "Envelope_list_WhitespaceOut__",
  "Envelope_list_WorkflowRunOut__",
  "Envelope_list_dict__",
  "ErrorBody",
  "ExpansionOutcomeIn",
  "ExpansionRecOut",
  "FeedbackIn",
  "FlagOut",
  "FlagUpdate",
  "ForecastOut",
  "GoogleConnectOut",
  "HTTPValidationError",
  "HandoffOut",
  "HealthOut",
  "HealthRebuildIn",
  "HealthRebuildOut",
  "ICPIn",
  "ICPOut",
  "ImportCommitIn",
  "ImportPreviewIn",
  "ImportPreviewOut",
  "InboxSimulateIn",
  "InboxSimulateOut",
  "IntegrationAccountOut",
  "KPIOut",
  "KnowledgeHit",
  "KnowledgeUploadResponse",
  "LeadIn",
  "LeadOut",
  "LeadScoreOut",
  "LifecycleLaneOut",
  "LifecycleOverview",
  "LoginRequest",
  "LoginResponse",
  "MarketIn",
  "MarketOut",
  "MarketOverview",
  "MeetingCaptureIn",
  "MeetingCaptureOut",
  "MeetingExtractIn",
  "MeetingIn",
  "MeetingOut",
  "MeetingTranscriptIn",
  "Meta",
  "MilestoneOut",
  "ModelCardOut",
  "ModelVersionOut",
  "NBAOut",
  "OpportunityIn",
  "OpportunityOut",
  "OverrideIn",
  "PilotActivateIn",
  "PilotActivateOut",
  "PilotCheckOut",
  "PilotReadinessOut",
  "PlaybookIn",
  "PlaybookOut",
  "PlaybookRunIn",
  "PostSaleAttentionOut",
  "PredictionOut",
  "ProductIn",
  "ProductOut",
  "PromoteIn",
  "ProviderActionOut",
  "ProviderHealthOut",
  "QuoteIn",
  "QuoteLineIn",
  "QuoteLineOut",
  "QuoteOut",
  "ReadinessOut",
  "ReferralIn",
  "ReferralOut",
  "RefreshOut",
  "RenewalOut",
  "RoleOut",
  "RollbackIn",
  "SearchHit",
  "SearchOut",
  "SequenceDetail",
  "SequenceIn",
  "SequenceOut",
  "SequenceStepIn",
  "SequenceStepOut",
  "SessionOut",
  "SignalOut",
  "StageMixOut",
  "SuccessObjectiveOut",
  "SuccessRow",
  "TaskIn",
  "TaskOut",
  "TeamIn",
  "TeamOut",
  "TerritoryIn",
  "TerritoryOut",
  "TimeToValueOut",
  "TimelineItemOut",
  "TokenUser",
  "TrainIn",
  "TriggerOut",
  "UsageSnapshotOut",
  "UsefulIn",
  "UserOut",
  "ValidationError",
  "VoiceDialIn",
  "VoiceDialOut",
  "VoiceScriptIn",
  "VoiceScriptOut",
  "VoiceScriptVersionOut",
  "WhatsAppTemplateIn",
  "WhatsAppTemplateOut",
  "WhitespaceOut",
  "WorkflowRunOut",
] as const;
