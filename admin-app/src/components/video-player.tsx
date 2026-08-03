"use client";

import { useState, useRef, useEffect, useImperativeHandle, forwardRef } from "react";
import { Play, Pause, Volume2, VolumeX, Maximize, SkipBack, SkipForward } from "lucide-react";

interface VideoPlayerProps {
  id: string;
  videoUrl: string;
  duration?: number;
  onTimeUpdate?: (currentTime: number) => void;
}

export interface VideoPlayerRef {
  seekTo: (time: number) => void;
}

export const VideoPlayer = forwardRef<VideoPlayerRef, VideoPlayerProps>(
  ({ id, videoUrl, duration, onTimeUpdate }, ref) => {
    const videoRef = useRef<HTMLVideoElement>(null);
    const [isPlaying, setIsPlaying] = useState(false);
    const [currentTime, setCurrentTime] = useState(0);
    const [videoDuration, setVideoDuration] = useState(duration || 0);
    const [isMuted, setIsMuted] = useState(false);
    const [showControls, setShowControls] = useState(true);
    const [videoError, setVideoError] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(true);

    useImperativeHandle(ref, () => ({
      seekTo: (time: number) => {
        if (videoRef.current) {
          videoRef.current.currentTime = time;
          setCurrentTime(time);
        }
      }
    }));

    useEffect(() => {
      const video = videoRef.current;
      if (!video) return;

      const handleTimeUpdate = () => {
        setCurrentTime(video.currentTime);
        onTimeUpdate?.(video.currentTime);
      };

      const handleLoadedMetadata = () => {
        setVideoDuration(video.duration);
      };

      const handleEnded = () => {
        setIsPlaying(false);
      };

      const handleError = () => {
        setVideoError("Unable to load video. The recording may have expired or is unavailable.");
        setIsLoading(false);
      };

      const handleCanPlay = () => {
        setIsLoading(false);
        setVideoError(null);
      };

      const handleLoadStart = () => {
        setIsLoading(true);
        setVideoError(null);
      };

      video.addEventListener("timeupdate", handleTimeUpdate);
      video.addEventListener("loadedmetadata", handleLoadedMetadata);
      video.addEventListener("ended", handleEnded);
      video.addEventListener("error", handleError);
      video.addEventListener("canplay", handleCanPlay);
      video.addEventListener("loadstart", handleLoadStart);

      return () => {
        video.removeEventListener("timeupdate", handleTimeUpdate);
        video.removeEventListener("loadedmetadata", handleLoadedMetadata);
        video.removeEventListener("ended", handleEnded);
        video.removeEventListener("error", handleError);
        video.removeEventListener("canplay", handleCanPlay);
        video.removeEventListener("loadstart", handleLoadStart);
      };
    }, [onTimeUpdate]);

    const togglePlay = async () => {
      const video = videoRef.current;
      if (!video || videoError) return;

      if (isPlaying) {
        video.pause();
        setIsPlaying(false);
      } else {
        try {
          await video.play();
          setIsPlaying(true);
        } catch (err) {
          console.error("Error playing video:", err);
          setVideoError("Unable to play video. Please try refreshing the page.");
        }
      }
    };

    const toggleMute = () => {
      const video = videoRef.current;
      if (!video) return;
      video.muted = !isMuted;
      setIsMuted(!isMuted);
    };

    const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
      const video = videoRef.current;
      if (!video) return;
      const time = parseFloat(e.target.value);
      video.currentTime = time;
      setCurrentTime(time);
    };

    const skip = (seconds: number) => {
      const video = videoRef.current;
      if (!video) return;
      video.currentTime = Math.max(0, Math.min(video.currentTime + seconds, videoDuration));
    };

    const formatTime = (seconds: number) => {
      const hrs = Math.floor(seconds / 3600);
      const mins = Math.floor((seconds % 3600) / 60);
      const secs = Math.floor(seconds % 60);
      if (hrs > 0) {
        return `${hrs}:${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
      }
      return `${mins}:${secs.toString().padStart(2, "0")}`;
    };

    const toggleFullscreen = () => {
      const container = document.getElementById(`${id}-container`);
      if (!container) return;
      if (document.fullscreenElement) {
        document.exitFullscreen();
      } else {
        container.requestFullscreen();
      }
    };

    return (
      <div
        id={`${id}-container`}
        className="relative bg-black rounded-xl overflow-hidden group"
        onMouseEnter={() => setShowControls(true)}
        onMouseLeave={() => setShowControls(!isPlaying)}
      >
        <video
          id={id}
          ref={videoRef}
          src={videoUrl}
          className="w-full aspect-video cursor-pointer"
          onClick={togglePlay}
          playsInline
        />

        {isLoading && !videoError && (
          <div id={`${id}-loading`} className="absolute inset-0 flex items-center justify-center bg-black/50">
            <div className="animate-spin rounded-full h-12 w-12 border-4 border-primary border-t-transparent" />
          </div>
        )}

        {videoError && (
          <div id={`${id}-error`} className="absolute inset-0 flex items-center justify-center bg-black/80">
            <div className="text-center p-6">
              <div className="text-red-400 text-lg mb-2">Video Unavailable</div>
              <div className="text-gray-400 text-sm">{videoError}</div>
            </div>
          </div>
        )}

        <div
          id={`${id}-controls`}
          className={`absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-4 transition-opacity duration-300 ${
            showControls ? "opacity-100" : "opacity-0"
          }`}
        >
          <div id={`${id}-progress`} className="mb-3">
            <input
              type="range"
              min={0}
              max={videoDuration || 100}
              value={currentTime}
              onChange={handleSeek}
              className="w-full h-1 bg-white/30 rounded-lg appearance-none cursor-pointer accent-primary"
              style={{
                background: `linear-gradient(to right, hsl(var(--primary)) ${(currentTime / (videoDuration || 1)) * 100}%, rgba(255,255,255,0.3) ${(currentTime / (videoDuration || 1)) * 100}%)`
              }}
            />
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <button
                id={`${id}-skip-back`}
                onClick={() => skip(-10)}
                className="text-white hover:text-primary transition-colors"
                title="Skip back 10s"
              >
                <SkipBack className="h-5 w-5" />
              </button>

              <button
                id={`${id}-play-pause`}
                onClick={togglePlay}
                className="text-white hover:text-primary transition-colors"
              >
                {isPlaying ? (
                  <Pause className="h-6 w-6" />
                ) : (
                  <Play className="h-6 w-6" />
                )}
              </button>

              <button
                id={`${id}-skip-forward`}
                onClick={() => skip(10)}
                className="text-white hover:text-primary transition-colors"
                title="Skip forward 10s"
              >
                <SkipForward className="h-5 w-5" />
              </button>

              <span id={`${id}-time`} className="text-white text-sm font-mono">
                {formatTime(currentTime)} / {formatTime(videoDuration)}
              </span>
            </div>

            <div className="flex items-center gap-3">
              <button
                id={`${id}-mute`}
                onClick={toggleMute}
                className="text-white hover:text-primary transition-colors"
              >
                {isMuted ? (
                  <VolumeX className="h-5 w-5" />
                ) : (
                  <Volume2 className="h-5 w-5" />
                )}
              </button>

              <button
                id={`${id}-fullscreen`}
                onClick={toggleFullscreen}
                className="text-white hover:text-primary transition-colors"
              >
                <Maximize className="h-5 w-5" />
              </button>
            </div>
          </div>
        </div>

        {!isPlaying && currentTime === 0 && (
          <div
            className="absolute inset-0 flex items-center justify-center cursor-pointer"
            onClick={togglePlay}
          >
            <div className="bg-primary/90 rounded-full p-4 hover:bg-primary transition-colors">
              <Play className="h-8 w-8 text-primary-foreground" />
            </div>
          </div>
        )}
      </div>
    );
  }
);

VideoPlayer.displayName = "VideoPlayer";
