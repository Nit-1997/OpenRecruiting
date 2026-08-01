export interface Profile {
  id: string;
  user_id: string;
  name: string;
  email: string;
  avatar_initials: string;
  avatar_color: string;
  timezone: string;
  onboarding_completed: boolean;
}

export interface NotificationPreferences {
  user_id: string;
  email_feedback_requests: boolean;
  email_interview_reminders: boolean;
  email_weekly_digest: boolean;
  slack_feedback_requests: boolean;
  slack_interview_reminders: boolean;
  slack_weekly_digest: boolean;
}
