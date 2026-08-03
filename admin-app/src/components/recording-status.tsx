"use client";

import { Video, Loader2, AlertCircle, Clock, CheckCircle2 } from "lucide-react";

interface RecordingStatusProps {
  candidateRoundId: string;
  status: string;
  scheduledAt: string | null;
}

const STATUS_CONFIG: Record<string, {
  icon: typeof Clock;
  color: string;
  bgColor: string;
  label: string;
  animate?: boolean;
  pulse?: boolean;
}> = {
  not_scheduled: {
    icon: Clock,
    color: "text-muted-foreground",
    bgColor: "bg-muted/50",
    label: "No recording scheduled"
  },
  created: {
    icon: Clock,
    color: "text-blue-500",
    bgColor: "bg-blue-50 dark:bg-blue-950/30",
    label: "Recording scheduled"
  },
  joining: {
    icon: Loader2,
    color: "text-yellow-500",
    bgColor: "bg-yellow-50 dark:bg-yellow-950/30",
    label: "Bot joining meeting...",
    animate: true
  },
  in_waiting_room: {
    icon: Clock,
    color: "text-orange-500",
    bgColor: "bg-orange-50 dark:bg-orange-950/30",
    label: "Waiting to be admitted"
  },
  in_call_not_recording: {
    icon: Video,
    color: "text-yellow-500",
    bgColor: "bg-yellow-50 dark:bg-yellow-950/30",
    label: "In call, preparing to record"
  },
  in_call_recording: {
    icon: Video,
    color: "text-red-500",
    bgColor: "bg-red-50 dark:bg-red-950/30",
    label: "Recording in progress",
    pulse: true
  },
  call_ended: {
    icon: Loader2,
    color: "text-blue-500",
    bgColor: "bg-blue-50 dark:bg-blue-950/30",
    label: "Processing recording...",
    animate: true
  },
  processing: {
    icon: Loader2,
    color: "text-blue-500",
    bgColor: "bg-blue-50 dark:bg-blue-950/30",
    label: "Processing...",
    animate: true
  },
  done: {
    icon: CheckCircle2,
    color: "text-green-500",
    bgColor: "bg-green-50 dark:bg-green-950/30",
    label: "Recording ready"
  },
  failed: {
    icon: AlertCircle,
    color: "text-red-500",
    bgColor: "bg-red-50 dark:bg-red-950/30",
    label: "Recording failed"
  },
  cancelled: {
    icon: AlertCircle,
    color: "text-muted-foreground",
    bgColor: "bg-muted/50",
    label: "Recording cancelled"
  }
};

export function RecordingStatus({ candidateRoundId, status, scheduledAt }: RecordingStatusProps) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.not_scheduled;
  const Icon = config.icon;

  return (
    <div
      id={`recording-status-${candidateRoundId}`}
      className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm ${config.bgColor}`}
    >
      <Icon
        className={`h-4 w-4 ${config.color} ${config.animate ? 'animate-spin' : ''} ${config.pulse ? 'animate-pulse' : ''}`}
      />
      <span className={config.color}>{config.label}</span>
      {scheduledAt && status === "created" && (
        <span className="text-xs text-muted-foreground ml-1">
          {new Date(scheduledAt).toLocaleString()}
        </span>
      )}
    </div>
  );
}
