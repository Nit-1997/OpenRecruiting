"use client";

import { useState, useEffect, useRef } from "react";
import { Search, Download, User } from "lucide-react";

interface TranscriptWord {
  text: string;
  start_timestamp: { relative: number; absolute?: string };
  end_timestamp: { relative: number; absolute?: string };
}

interface TranscriptSegment {
  participant: {
    id: string;
    name: string;
    is_host?: boolean;
  };
  words: TranscriptWord[];
}

interface TranscriptViewerProps {
  id: string;
  transcript: TranscriptSegment[];
  currentVideoTime?: number;
  onSeek?: (timestamp: number) => void;
}

export function TranscriptViewer({
  id,
  transcript,
  currentVideoTime = 0,
  onSeek
}: TranscriptViewerProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [activeSegmentIndex, setActiveSegmentIndex] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!transcript || transcript.length === 0) return;

    let foundIndex = -1;
    for (let i = 0; i < transcript.length; i++) {
      const segment = transcript[i];
      if (segment.words && segment.words.length > 0) {
        const startTime = segment.words[0].start_timestamp.relative;
        const endTime = segment.words[segment.words.length - 1].end_timestamp.relative;

        if (currentVideoTime >= startTime && currentVideoTime <= endTime) {
          foundIndex = i;
          break;
        }
      }
    }

    if (foundIndex !== activeSegmentIndex) {
      setActiveSegmentIndex(foundIndex);

      if (foundIndex >= 0 && containerRef.current) {
        const activeElement = containerRef.current.querySelector(`[data-segment-index="${foundIndex}"]`);
        if (activeElement) {
          activeElement.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      }
    }
  }, [currentVideoTime, transcript, activeSegmentIndex]);

  const formatTimestamp = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  const getSegmentText = (segment: TranscriptSegment) => {
    if (!segment.words) return "";
    return segment.words.map(w => w.text).join(" ");
  };

  const filteredTranscript = searchQuery
    ? transcript.filter(segment =>
        getSegmentText(segment).toLowerCase().includes(searchQuery.toLowerCase()) ||
        segment.participant?.name?.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : transcript;

  const handleSegmentClick = (segment: TranscriptSegment) => {
    if (segment.words && segment.words.length > 0 && onSeek) {
      onSeek(segment.words[0].start_timestamp.relative);
    }
  };

  const downloadTranscript = () => {
    const text = transcript.map(segment => {
      const timestamp = segment.words?.[0]?.start_timestamp?.relative || 0;
      const speakerName = segment.participant?.name || "Scout AI";
      return `[${formatTimestamp(timestamp)}] ${speakerName}: ${getSegmentText(segment)}`;
    }).join("\n\n");

    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "interview-transcript.txt";
    a.click();
    URL.revokeObjectURL(url);
  };

  if (!transcript || transcript.length === 0) {
    return (
      <div id={id} className="flex items-center justify-center h-full text-muted-foreground">
        No transcript available
      </div>
    );
  }

  return (
    <div id={id} className="flex flex-col h-full">
      <div id={`${id}-header`} className="flex items-center gap-2 pb-3 border-b border-border mb-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            id={`${id}-search`}
            type="text"
            placeholder="Search transcript..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-3 py-2 text-sm bg-muted/50 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
        <button
          id={`${id}-download`}
          onClick={downloadTranscript}
          className="p-2 hover:bg-muted rounded-lg transition-colors"
          title="Download transcript"
        >
          <Download className="h-4 w-4" />
        </button>
      </div>

      <div
        id={`${id}-content`}
        ref={containerRef}
        className="flex-1 overflow-y-auto space-y-3 pr-2"
      >
        {filteredTranscript.map((segment, index) => {
          const originalIndex = searchQuery
            ? transcript.indexOf(segment)
            : index;
          const isActive = originalIndex === activeSegmentIndex;
          const timestamp = segment.words?.[0]?.start_timestamp?.relative || 0;
          const speakerName = segment.participant?.name || "Scout AI";

          return (
            <div
              key={index}
              data-segment-index={originalIndex}
              id={`${id}-segment-${index}`}
              onClick={() => handleSegmentClick(segment)}
              className={`p-3 rounded-lg cursor-pointer transition-all ${
                isActive
                  ? "bg-primary/10 border-l-4 border-primary"
                  : "hover:bg-muted/50 border-l-4 border-transparent"
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                <User className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                <span className="font-medium text-sm truncate">{speakerName}</span>
                <span className="text-xs text-muted-foreground font-mono flex-shrink-0">
                  {formatTimestamp(timestamp)}
                </span>
              </div>
              <p className="text-sm text-foreground/80 leading-relaxed pl-6">
                {getSegmentText(segment)}
              </p>
            </div>
          );
        })}
      </div>

      {searchQuery && filteredTranscript.length === 0 && (
        <div className="text-center py-8 text-muted-foreground">
          No results found for "{searchQuery}"
        </div>
      )}
    </div>
  );
}
