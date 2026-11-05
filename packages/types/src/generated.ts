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
  "/api/v1/acquisition/form-keys/{key_id}": "patch";
  "/api/v1/acquisition/form-keys/{key_id}/revoke": "post";
  "/api/v1/acquisition/interest-form": "get";
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
  "/api/v1/ai/drafts/whatsapp": "post";
  "/api/v1/ai/knowledge": "get, post";
  "/api/v1/ai/knowledge/search": "get";
  "/api/v1/ai/knowledge/{source_id}": "get";
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
  "/api/v1/channel-search": "get, post";
  "/api/v1/channel-search/snippet": "post";
  "/api/v1/channel-search/status": "get";
  "/api/v1/command-center/activity": "get";
  "/api/v1/command-center/kpis": "get";
  "/api/v1/command-center/operations": "get";
  "/api/v1/command-center/overview": "get";
  "/api/v1/command-center/pipeline-mix": "get";
  "/api/v1/command-center/work-queue": "get";
  "/api/v1/contacts": "get, post";
  "/api/v1/contacts/{contact_id}": "get, patch";
  "/api/v1/content/drafts": "get";
  "/api/v1/content/drafts/{draft_id}": "patch";
  "/api/v1/content/drafts/{draft_id}/publish": "post";
  "/api/v1/content/generate": "post";
  "/api/v1/content/products": "get, post";
  "/api/v1/content/products/{product_id}": "patch";
  "/api/v1/content/profile": "get, put";
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
  "/api/v1/integrations/channels": "get";
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
  "/api/v1/journeys/meetings/{meeting_id}/cancel": "post";
  "/api/v1/journeys/meetings/{meeting_id}/reschedule": "post";
  "/api/v1/journeys/{run_id}/cancel": "post";
  "/api/v1/journeys/{run_id}/continue": "post";
  "/api/v1/journeys/{run_id}/next-action": "get";
  "/api/v1/journeys/{run_id}/pause": "post";
  "/api/v1/journeys/{run_id}/resume": "post";
  "/api/v1/leads": "get, post";
  "/api/v1/leads/assignees": "get";
  "/api/v1/leads/{lead_id}": "get, patch";
  "/api/v1/leads/{lead_id}/assessment": "get";
  "/api/v1/leads/{lead_id}/assign": "post";
  "/api/v1/leads/{lead_id}/discovery-booking": "post";
  "/api/v1/leads/{lead_id}/enrich": "post";
  "/api/v1/leads/{lead_id}/nba": "post";
  "/api/v1/leads/{lead_id}/sales-qualification": "post";
  "/api/v1/leads/{lead_id}/score": "post";
  "/api/v1/lifecycle/abm": "get, post";
  "/api/v1/lifecycle/accounts/{account_id}": "get";
  "/api/v1/lifecycle/advocacy": "get, post";
  "/api/v1/lifecycle/advocacy/referrals": "post";
  "/api/v1/lifecycle/campaigns": "get, post";
  "/api/v1/lifecycle/campaigns/{campaign_id}": "get";
  "/api/v1/lifecycle/campaigns/{campaign_id}/assemble": "post";
  "/api/v1/lifecycle/campaigns/{campaign_id}/audience": "post";
  "/api/v1/lifecycle/campaigns/{campaign_id}/creative": "post";
  "/api/v1/lifecycle/campaigns/{campaign_id}/launch": "post";
  "/api/v1/lifecycle/campaigns/{campaign_id}/members": "post";
  "/api/v1/lifecycle/campaigns/{campaign_id}/pause": "post";
  "/api/v1/lifecycle/campaigns/{campaign_id}/sync": "post";
  "/api/v1/lifecycle/captures/{capture_id}/refresh": "post";
  "/api/v1/lifecycle/commercial-ledger": "get";
  "/api/v1/lifecycle/conversations": "get, post";
  "/api/v1/lifecycle/conversations/dial": "post";
  "/api/v1/lifecycle/conversations/{conversation_id}": "get";
  "/api/v1/lifecycle/deals": "get";
  "/api/v1/lifecycle/deals/rescore": "post";
  "/api/v1/lifecycle/dograh/browser-test": "get";
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
  "/api/v1/lifecycle/onboarding/{plan_id}/complete": "post";
  "/api/v1/lifecycle/onboarding/{plan_id}/correct": "post";
  "/api/v1/lifecycle/onboarding/{plan_id}/items/{item_id}/evidence": "post";
  "/api/v1/lifecycle/onboarding/{plan_id}/items/{item_id}/review": "post";
  "/api/v1/lifecycle/onboarding/{plan_id}/items/{item_id}/waive": "post";
  "/api/v1/lifecycle/opportunities/{opportunity_id}/commercial": "get";
  "/api/v1/lifecycle/overview": "get";
  "/api/v1/lifecycle/playbooks": "get, post";
  "/api/v1/lifecycle/playbooks/runs": "get";
  "/api/v1/lifecycle/playbooks/{playbook_id}/run": "post";
  "/api/v1/lifecycle/products": "get, post";
  "/api/v1/lifecycle/purchases/{purchase_id}/followthrough": "get";
  "/api/v1/lifecycle/purchases/{purchase_id}/health": "post";
  "/api/v1/lifecycle/purchases/{purchase_id}/retention-review": "post";
  "/api/v1/lifecycle/quotes": "get, post";
  "/api/v1/lifecycle/quotes/{quote_id}": "get";
  "/api/v1/lifecycle/quotes/{quote_id}/issue": "post";
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
  "/api/v1/operating-plans/authorize": "post";
  "/api/v1/operating-plans/calendar": "post";
  "/api/v1/operating-plans/drafts": "post";
  "/api/v1/operating-plans/evidence": "get";
  "/api/v1/operating-plans/lead-forms": "post";
  "/api/v1/operating-plans/metrics": "post";
  "/api/v1/operating-plans/metrics/collect": "post";
  "/api/v1/operating-plans/outcomes": "get";
  "/api/v1/operating-plans/proposals/promote": "post";
  "/api/v1/operating-plans/proposals/{proposal_id}/preview": "post";
  "/api/v1/operating-plans/publish": "post";
  "/api/v1/operating-plans/readiness": "get";
  "/api/v1/operating-plans/research": "post";
  "/api/v1/operating-plans/resume": "post";
  "/api/v1/operating-plans/review": "get";
  "/api/v1/operating-plans/revise": "post";
  "/api/v1/operating-plans/schedule": "get, post";
  "/api/v1/operating-plans/start": "post";
  "/api/v1/opportunities": "get, post";
  "/api/v1/opportunities/{opportunity_id}": "get, patch";
  "/api/v1/opportunities/{opportunity_id}/close-lost": "post";
  "/api/v1/opportunities/{opportunity_id}/close-won": "post";
  "/api/v1/opportunities/{opportunity_id}/close-won/correct": "post";
  "/api/v1/opportunities/{opportunity_id}/commercial": "get";
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
  "/api/v1/public/forms/{token}/meta": "get";
  "/api/v1/public/media/{token}": "get";
  "/api/v1/public/r/{token}": "get";
  "/api/v1/search": "get";
  "/api/v1/site-signals": "get";
  "/api/v1/site-signals/cohort": "post";
  "/api/v1/site-signals/profile": "post";
  "/api/v1/site-signals/status": "post";
  "/api/v1/social-growth/accounts": "get, post";
  "/api/v1/social-growth/accounts/fixture": "post";
  "/api/v1/social-growth/accounts/{account_id}": "patch";
  "/api/v1/social-growth/accounts/{account_id}/disconnect": "post";
  "/api/v1/social-growth/accounts/{account_id}/history": "post";
  "/api/v1/social-growth/accounts/{account_id}/insights": "post";
  "/api/v1/social-growth/accounts/{account_id}/verify": "post";
  "/api/v1/social-growth/attribution": "get";
  "/api/v1/social-growth/brand": "get";
  "/api/v1/social-growth/brand/analyze": "post";
  "/api/v1/social-growth/brand/competitors": "post";
  "/api/v1/social-growth/brand/facts": "post";
  "/api/v1/social-growth/brand/facts/review": "post";
  "/api/v1/social-growth/brand/settings": "put";
  "/api/v1/social-growth/calendar": "get";
  "/api/v1/social-growth/calendar/plan": "post";
  "/api/v1/social-growth/calendar/{item_id}/creative": "post";
  "/api/v1/social-growth/calendar/{item_id}/publish": "post";
  "/api/v1/social-growth/calendar/{item_id}/schedule": "post";
  "/api/v1/social-growth/calendar/{item_id}/skip": "post";
  "/api/v1/social-growth/creatives/review": "get";
  "/api/v1/social-growth/creatives/{creative_id}": "get, patch";
  "/api/v1/social-growth/creatives/{creative_id}/review": "post";
  "/api/v1/social-growth/events": "post";
  "/api/v1/social-growth/events/{event_id}": "delete";
  "/api/v1/social-growth/ga4/collect": "post";
  "/api/v1/social-growth/grants": "get, post";
  "/api/v1/social-growth/grants/{grant_id}/revoke": "post";
  "/api/v1/social-growth/overview": "get";
  "/api/v1/social-growth/performance": "get";
  "/api/v1/social-growth/publications": "get";
  "/api/v1/social-growth/publications/{publication_id}/resolve": "post";
  "/api/v1/social-growth/recommendations": "get";
  "/api/v1/social-growth/recommendations/generate": "post";
  "/api/v1/social-growth/recommendations/{recommendation_id}/decide": "post";
  "/api/v1/social-growth/strategy": "get, put";
  "/api/v1/social-growth/strategy/pause": "post";
  "/api/v1/social-growth/strategy/{strategy_id}/approve": "post";
  "/api/v1/social/banner": "post";
  "/api/v1/social/compose": "post";
  "/api/v1/social/draft": "post";
  "/api/v1/social/images": "post";
  "/api/v1/social/posts": "get, post";
  "/api/v1/social/posts/{post_id}": "patch";
  "/api/v1/social/posts/{post_id}/revision": "post";
  "/api/v1/social/status": "get";
  "/api/v1/social/submissions": "post";
  "/api/v1/social/video": "post";
  "/api/v1/tasks": "get, post";
  "/api/v1/tasks/{task_id}": "get, patch";
  "/api/v1/webhooks/meta/leadgen": "get, post";
  "/api/v1/webhooks/{provider}/{routing_token}": "post";
  "/api/v1/workflow/campaign-plans": "post";
  "/api/v1/workflow/command": "get";
  "/api/v1/workflow/events/{event_id}/replay": "post";
  "/api/v1/workflow/grants": "post";
  "/api/v1/workflow/invitations": "post";
  "/api/v1/workflow/invitations/{invitation_id}/accept": "post";
  "/api/v1/workflow/launch": "get";
  "/api/v1/workflow/meetings/{meeting_id}/outcome": "post";
  "/api/v1/workflow/objectives": "post";
  "/api/v1/workflow/operations": "get";
  "/api/v1/workflow/operations/evidence": "post";
  "/api/v1/workflow/opportunities/{opportunity_id}/advance": "post";
  "/api/v1/workflow/quotes/{quote_id}/accept": "post";
  "/api/v1/workflow/quotes/{quote_id}/acceptance/review": "post";
  "/api/v1/workflow/retention": "get";
  "/api/v1/workflow/sequences/{sequence_id}/activate": "post";
  "/api/v1/workflow/users/{user_id}/deactivate": "post";
  "/health": "get";
  "/health/live": "get";
  "/health/ready": "get";
  "/metrics": "get";
  "/ready": "get";
};

export const generatedPathCount = 318;
export const generatedSchemaNames = [
  "AbmIn",
  "AbmOut",
  "AcceptIn",
  "AcceptanceReviewIn",
  "AccountContextOut",
  "AccountIn",
  "AccountLifecycleOut",
  "AccountOut",
  "AccountUpdateIn",
  "AcquisitionOverview",
  "ActivityOut",
  "AdvocacyIn",
  "AdvocacyOut",
  "AnalyzeIn",
  "ApprovalDecision",
  "ApprovalOut",
  "AssessmentOut",
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
  "Body_preview_api_v1_operating_plans_proposals__proposal_id__preview_post",
  "Body_upload_knowledge_api_v1_ai_knowledge_post",
  "Body_upload_social_image_api_v1_social_images_post",
  "BrandFactIn",
  "BrandSettingsIn",
  "BriefOut",
  "CadenceIn",
  "CalendarBookIn",
  "CalendarBookOut",
  "CalendarIn",
  "CampaignDetail",
  "CampaignEnquiry",
  "CampaignIn",
  "CampaignLaunchOut",
  "CampaignMemberIn",
  "CampaignMemberOut",
  "CampaignOut",
  "CampaignPlanIn",
  "CaptionIn",
  "CaptureIn",
  "CaptureOut",
  "CaptureResult",
  "ChannelBucketOut",
  "ChannelHitOut",
  "ChannelSearchIn",
  "ChannelSearchOut",
  "ChannelSearchStatusOut",
  "ChurnIn",
  "CloseLostIn",
  "CloseWonCorrectionIn",
  "CloseWonIn",
  "CohortAccountOut",
  "CohortIn",
  "CohortOut",
  "CohortSignalOut",
  "CommercialViewOut",
  "CompetitorsIn",
  "ConnectorOut",
  "ContactIn",
  "ContactOut",
  "ContentDraftOut",
  "ContentDraftPatch",
  "ContentProductIn",
  "ContentProductOut",
  "ContentProductPatch",
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
  "DecideIn",
  "DedupeDecision",
  "DedupeOut",
  "DiscoveryBookingIn",
  "DiscoveryBookingOut",
  "DiscoveryHealthOut",
  "DiscoveryProspectOut",
  "DiscoveryRunIn",
  "DiscoveryRunOut",
  "DograhBrowserTestOut",
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
  "Envelope_AssessmentOut_",
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
  "Envelope_ChannelSearchOut_",
  "Envelope_ChannelSearchStatusOut_",
  "Envelope_CohortOut_",
  "Envelope_CommercialViewOut_",
  "Envelope_ContactOut_",
  "Envelope_ContentDraftOut_",
  "Envelope_ContentProductOut_",
  "Envelope_ConversationOut_",
  "Envelope_CopilotResponse_",
  "Envelope_Customer360Out_",
  "Envelope_CustomerOut_",
  "Envelope_DatasetOut_",
  "Envelope_DedupeOut_",
  "Envelope_DiscoveryBookingOut_",
  "Envelope_DiscoveryHealthOut_",
  "Envelope_DiscoveryRunOut_",
  "Envelope_DograhBrowserTestOut_",
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
  "Envelope_JourneyContinueOut_",
  "Envelope_JourneyControlOut_",
  "Envelope_KPIOut_",
  "Envelope_KnowledgeSourceDetail_",
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
  "Envelope_NextActionOut_",
  "Envelope_OpportunityOut_",
  "Envelope_PilotActivateOut_",
  "Envelope_PilotReadinessOut_",
  "Envelope_PlaybookOut_",
  "Envelope_PostSaleAttentionOut_",
  "Envelope_ProductOut_",
  "Envelope_ProviderActionOut_",
  "Envelope_PublicFormOut_",
  "Envelope_QuoteOut_",
  "Envelope_ReferralOut_",
  "Envelope_RefreshOut_",
  "Envelope_RenewalOut_",
  "Envelope_SalesQualificationOut_",
  "Envelope_SearchOut_",
  "Envelope_SellerProfileOut_",
  "Envelope_SequenceDetail_",
  "Envelope_SiteProfileRunOut_",
  "Envelope_SiteSignalBoardOut_",
  "Envelope_SnippetExpandOut_",
  "Envelope_SocialComposeOut_",
  "Envelope_SocialCreativeOut_",
  "Envelope_SocialDraftOut_",
  "Envelope_SocialPostOut_",
  "Envelope_SocialSubmissionOut_",
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
  "Envelope_list_ChannelSearchOut__",
  "Envelope_list_ConnectorOut__",
  "Envelope_list_ContactOut__",
  "Envelope_list_ContentDraftOut__",
  "Envelope_list_ContentProductOut__",
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
  "Envelope_list_LeadAssigneeOut__",
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
  "Envelope_list_PublicFormOut__",
  "Envelope_list_QuoteOut__",
  "Envelope_list_ReadinessOut__",
  "Envelope_list_RenewalOut__",
  "Envelope_list_RoleOut__",
  "Envelope_list_SequenceOut__",
  "Envelope_list_SessionOut__",
  "Envelope_list_SignalOut__",
  "Envelope_list_SocialChannelStatus__",
  "Envelope_list_SocialPostOut__",
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
  "EventIn",
  "EvidenceIn",
  "ExpansionOutcomeIn",
  "ExpansionRecOut",
  "FactIn",
  "FactOut",
  "FactReviewIn",
  "FeedbackIn",
  "FixtureAccountIn",
  "FlagOut",
  "FlagUpdate",
  "ForecastOut",
  "GenerateContentIn",
  "GoogleConnectOut",
  "GrantIn",
  "GrowthAccountIn",
  "GrowthGrantIn",
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
  "InviteIn",
  "JourneyContinueOut",
  "JourneyControlOut",
  "KPIOut",
  "KnowledgeHit",
  "KnowledgeSourceDetail",
  "KnowledgeUploadResponse",
  "LeadAssign",
  "LeadAssigneeOut",
  "LeadFormIn",
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
  "MeetingOutcomeIn",
  "MeetingSlot",
  "MeetingTranscriptIn",
  "Meta",
  "MetricsIn",
  "MilestoneOut",
  "ModelCardOut",
  "ModelVersionOut",
  "NBAOut",
  "NextActionOut",
  "ObjectiveIn",
  "OnboardingCompleteIn",
  "OnboardingEvidenceIn",
  "OnboardingNoteIn",
  "OnboardingReasonIn",
  "OpportunityIn",
  "OpportunityOut",
  "OverrideIn",
  "PauseIn",
  "PillarIn",
  "PilotActivateIn",
  "PilotActivateOut",
  "PilotCheckOut",
  "PilotReadinessOut",
  "PlaybookIn",
  "PlaybookOut",
  "PlaybookRunIn",
  "PostSaleAttentionOut",
  "PostingWindow",
  "PredictionOut",
  "ProductIn",
  "ProductOut",
  "PromoteIn",
  "ProposalIn",
  "ProviderActionOut",
  "ProviderHealthOut",
  "PublicFormField",
  "PublicFormIn",
  "PublicFormOut",
  "PublicFormPatch",
  "PurchaseHealthIn",
  "QuoteAcceptIn",
  "QuoteIn",
  "QuoteLineIn",
  "QuoteLineOut",
  "QuoteOut",
  "ReadinessOut",
  "ReferralIn",
  "ReferralOut",
  "RefreshOut",
  "RenewalOut",
  "ResolveIn",
  "ReviewIn",
  "RoleOut",
  "RollbackIn",
  "SalesQualificationIn",
  "SalesQualificationOut",
  "SearchHit",
  "SearchOut",
  "SellerProfileIn",
  "SellerProfileOut",
  "SequenceDetail",
  "SequenceIn",
  "SequenceOut",
  "SequenceStepIn",
  "SequenceStepOut",
  "SessionOut",
  "SignalOut",
  "SiteObservationOut",
  "SiteProfileIn",
  "SiteProfileRunOut",
  "SiteSignalBoardOut",
  "SiteSignalOut",
  "SiteSignalStatusIn",
  "SkipIn",
  "SnippetExpandIn",
  "SnippetExpandOut",
  "SocialBriefIn",
  "SocialChannelStatus",
  "SocialComposeOut",
  "SocialCreativeIn",
  "SocialCreativeOut",
  "SocialDraftIn",
  "SocialDraftOut",
  "SocialExtraLink",
  "SocialPostIn",
  "SocialPostOut",
  "SocialPostUpdate",
  "SocialSubmissionIn",
  "SocialSubmissionOut",
  "StageAdvanceIn",
  "StageMixOut",
  "StrategyIn",
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
  "VersionIn",
  "VoiceDialIn",
  "VoiceDialOut",
  "VoiceHandoffOut",
  "VoiceScriptIn",
  "VoiceScriptOut",
  "VoiceScriptVersionOut",
  "WhatsAppDraftRequest",
  "WhatsAppTemplateIn",
  "WhatsAppTemplateOut",
  "WhitespaceOut",
  "WorkflowRunOut",
] as const;
