"use client";

import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Color from "@tiptap/extension-color";
import { TextStyle } from "@tiptap/extension-text-style";
import Highlight from "@tiptap/extension-highlight";
import Underline from "@tiptap/extension-underline";
import TextAlign from "@tiptap/extension-text-align";
import Link from "@tiptap/extension-link";
import Image from "@tiptap/extension-image";
import Youtube from "@tiptap/extension-youtube";
import Placeholder from "@tiptap/extension-placeholder";
import { useRef, useCallback } from "react";
import {
  Bold,
  Italic,
  Underline as UnderlineIcon,
  Strikethrough,
  Heading1,
  Heading2,
  Heading3,
  List,
  ListOrdered,
  Quote,
  Code,
  AlignLeft,
  AlignCenter,
  AlignRight,
  Link as LinkIcon,
  ImageIcon,
  Youtube as YoutubeIcon,
  Music,
  Minus,
  Highlighter,
  Palette,
} from "lucide-react";

interface RichEditorProps {
  content: string;
  onChange: (html: string) => void;
  onUploadImage: (file: File) => Promise<string>;
  placeholder?: string;
}

export function RichEditor({
  content,
  onChange,
  onUploadImage,
  placeholder = "Write your post...",
}: RichEditorProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
      }),
      TextStyle,
      Color,
      Highlight.configure({ multicolor: true }),
      Underline,
      TextAlign.configure({ types: ["heading", "paragraph"] }),
      Link.configure({ openOnClick: false }),
      Image,
      Youtube.configure({ width: 640, height: 360 }),
      Placeholder.configure({ placeholder }),
    ],
    content,
    onUpdate: ({ editor }) => {
      onChange(editor.getHTML());
    },
    immediatelyRender: false,
    editorProps: {
      attributes: {
        class: "tiptap-editor prose text-foreground",
      },
    },
  });

  const uploadImage = useCallback(
    async (file: File) => {
      if (!editor) return;
      try {
        const url = await onUploadImage(file);
        editor.chain().focus().setImage({ src: url }).run();
      } catch {
        alert("Upload failed");
      }
    },
    [editor, onUploadImage]
  );

  if (!editor) return null;

  function addLink() {
    const prev = editor!.getAttributes("link").href || "";
    const url = window.prompt("Enter URL:", prev);
    if (url === null) return;
    if (url === "") {
      editor!.chain().focus().extendMarkRange("link").unsetLink().run();
    } else {
      editor!.chain().focus().extendMarkRange("link").setLink({ href: url }).run();
    }
  }

  function addYoutube() {
    const url = window.prompt("Enter YouTube URL:");
    if (!url) return;
    editor!.commands.setYoutubeVideo({ src: url });
  }

  function addAudio() {
    const url = window.prompt("Enter audio URL (mp3, wav, etc.):");
    if (!url) return;
    editor!
      .chain()
      .focus()
      .insertContent(
        `<audio controls src="${url}" style="width:100%;max-width:500px;margin:1rem 0;"></audio>`
      )
      .run();
  }

  return (
    <div id="rich-editor-wrapper" className="rich-editor-wrapper rounded-md border border-border bg-background overflow-hidden">
      <Toolbar
        editor={editor}
        onImageClick={() => fileInputRef.current?.click()}
        onLinkClick={addLink}
        onYoutubeClick={addYoutube}
        onAudioClick={addAudio}
      />
      <EditorContent editor={editor} />
      <input
        id="rich-editor-file-input"
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) uploadImage(file);
          e.target.value = "";
        }}
      />
    </div>
  );
}

function ToolbarButton({
  onClick,
  active,
  title,
  children,
}: {
  onClick: () => void;
  active?: boolean;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={`p-1.5 rounded hover:bg-accent transition-colors ${
        active ? "bg-accent text-accent-foreground" : "text-muted-foreground"
      }`}
    >
      {children}
    </button>
  );
}

function Divider() {
  return <div className="w-px h-6 bg-border mx-1" />;
}

function Toolbar({
  editor,
  onImageClick,
  onLinkClick,
  onYoutubeClick,
  onAudioClick,
}: {
  editor: ReturnType<typeof useEditor> & object;
  onImageClick: () => void;
  onLinkClick: () => void;
  onYoutubeClick: () => void;
  onAudioClick: () => void;
}) {
  const iconSize = 16;

  return (
    <div id="rich-editor-toolbar" className="editor-toolbar flex flex-wrap items-center gap-0.5 border-b border-border px-2 py-1.5 bg-secondary/30">
      <ToolbarButton onClick={() => editor.chain().focus().toggleBold().run()} active={editor.isActive("bold")} title="Bold">
        <Bold size={iconSize} />
      </ToolbarButton>
      <ToolbarButton onClick={() => editor.chain().focus().toggleItalic().run()} active={editor.isActive("italic")} title="Italic">
        <Italic size={iconSize} />
      </ToolbarButton>
      <ToolbarButton onClick={() => editor.chain().focus().toggleUnderline().run()} active={editor.isActive("underline")} title="Underline">
        <UnderlineIcon size={iconSize} />
      </ToolbarButton>
      <ToolbarButton onClick={() => editor.chain().focus().toggleStrike().run()} active={editor.isActive("strike")} title="Strikethrough">
        <Strikethrough size={iconSize} />
      </ToolbarButton>
      <Divider />
      <ToolbarButton onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()} active={editor.isActive("heading", { level: 1 })} title="Heading 1">
        <Heading1 size={iconSize} />
      </ToolbarButton>
      <ToolbarButton onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} active={editor.isActive("heading", { level: 2 })} title="Heading 2">
        <Heading2 size={iconSize} />
      </ToolbarButton>
      <ToolbarButton onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()} active={editor.isActive("heading", { level: 3 })} title="Heading 3">
        <Heading3 size={iconSize} />
      </ToolbarButton>
      <Divider />
      <ToolbarButton onClick={() => editor.chain().focus().toggleBulletList().run()} active={editor.isActive("bulletList")} title="Bullet List">
        <List size={iconSize} />
      </ToolbarButton>
      <ToolbarButton onClick={() => editor.chain().focus().toggleOrderedList().run()} active={editor.isActive("orderedList")} title="Ordered List">
        <ListOrdered size={iconSize} />
      </ToolbarButton>
      <ToolbarButton onClick={() => editor.chain().focus().toggleBlockquote().run()} active={editor.isActive("blockquote")} title="Blockquote">
        <Quote size={iconSize} />
      </ToolbarButton>
      <ToolbarButton onClick={() => editor.chain().focus().toggleCodeBlock().run()} active={editor.isActive("codeBlock")} title="Code Block">
        <Code size={iconSize} />
      </ToolbarButton>
      <ToolbarButton onClick={() => editor.chain().focus().setHorizontalRule().run()} title="Horizontal Rule">
        <Minus size={iconSize} />
      </ToolbarButton>
      <Divider />
      <ToolbarButton onClick={() => editor.chain().focus().setTextAlign("left").run()} active={editor.isActive({ textAlign: "left" })} title="Align Left">
        <AlignLeft size={iconSize} />
      </ToolbarButton>
      <ToolbarButton onClick={() => editor.chain().focus().setTextAlign("center").run()} active={editor.isActive({ textAlign: "center" })} title="Align Center">
        <AlignCenter size={iconSize} />
      </ToolbarButton>
      <ToolbarButton onClick={() => editor.chain().focus().setTextAlign("right").run()} active={editor.isActive({ textAlign: "right" })} title="Align Right">
        <AlignRight size={iconSize} />
      </ToolbarButton>
      <Divider />
      <label id="rich-editor-text-color" title="Text Color" className="relative p-1.5 rounded hover:bg-accent transition-colors text-muted-foreground cursor-pointer">
        <Palette size={iconSize} />
        <input type="color" className="absolute inset-0 opacity-0 cursor-pointer w-full h-full" onChange={(e) => editor.chain().focus().setColor(e.target.value).run()} />
      </label>
      <label id="rich-editor-highlight-color" title="Highlight Color" className="relative p-1.5 rounded hover:bg-accent transition-colors text-muted-foreground cursor-pointer">
        <Highlighter size={iconSize} />
        <input type="color" defaultValue="#fef08a" className="absolute inset-0 opacity-0 cursor-pointer w-full h-full" onChange={(e) => editor.chain().focus().toggleHighlight({ color: e.target.value }).run()} />
      </label>
      <Divider />
      <ToolbarButton onClick={onLinkClick} active={editor.isActive("link")} title="Insert Link">
        <LinkIcon size={iconSize} />
      </ToolbarButton>
      <ToolbarButton onClick={onImageClick} title="Upload Image">
        <ImageIcon size={iconSize} />
      </ToolbarButton>
      <ToolbarButton onClick={onYoutubeClick} title="Embed YouTube Video">
        <YoutubeIcon size={iconSize} />
      </ToolbarButton>
      <ToolbarButton onClick={onAudioClick} title="Embed Audio">
        <Music size={iconSize} />
      </ToolbarButton>
    </div>
  );
}
