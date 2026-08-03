"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <button
        id="theme-toggle-btn"
        className="h-10 w-10 flex items-center justify-center rounded-lg hover:bg-secondary transition-colors"
      >
        <Sun className="h-5 w-5" />
      </button>
    );
  }

  return (
    <button
      id="theme-toggle-btn"
      className="h-10 w-10 flex items-center justify-center rounded-lg hover:bg-secondary transition-colors"
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
    >
      {theme === "dark" ? (
        <Sun id="theme-icon-sun" className="h-5 w-5" />
      ) : (
        <Moon id="theme-icon-moon" className="h-5 w-5" />
      )}
      <span className="sr-only">Toggle theme</span>
    </button>
  );
}
