"use client";

import { useState, useCallback } from "react";
import { motion } from "framer-motion";
import { Badge } from "@/components/ui/badge";
import { formatNumber, entityTypeColor, sentimentColor, sentimentLabel } from "@/lib/utils";
import { useAuth } from "@/components/auth/auth-provider";
import { authApi } from "@/lib/auth";
import { MessageEditModal } from "@/components/admin/message-edit-modal";
import { SourceStatusBadge } from "@/components/topics/source-status-badge";
import { useDemoContext } from "@/components/providers";
import type { Message } from "@/types";
import {
  Clock,
  ExternalLink,
  Eye,
  Forward,
  Network,
  Pencil,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { format, parseISO } from "date-fns";
import Link from "next/link";

interface Props {
  message: Message;
  index: number;
}

function telegramUrl(message: Message): string | null {
  if (message.permalink) return message.permalink;

  const channel = message.channel
    .replace(/^@/, "")
    .replace(/^https?:\/\/t\.me\//, "")
    .replace(/^t\.me\//, "")
    .split("/")[0]
    ?.trim();

  if (!channel || channel.startsWith("-") || !message.message_id) return null;
  return `https://t.me/${channel}/${message.message_id}`;
}

function entityHref(entityId: string): string {
  return `/entities/${encodeURIComponent(entityId)}`;
}

function graphHref(message: Message): string | null {
  if (!message.cluster_id) return null;
  const params = new URLSearchParams({
    mode: "propagation",
    clusterId: message.cluster_id,
    focus: `msg-${message.event_id}`,
  });
  return `/graph?${params.toString()}`;
}

export function MessageCard({ message, index }: Props) {
  const { user, isAdmin } = useAuth();
  const { setIsDemo } = useDemoContext();
  const sentColor = sentimentColor(message.sentiment_score || 0);
  const sentLbl = sentimentLabel(message.sentiment_score || 0);
  const sourceUrl = telegramUrl(message);
  const graphUrl = graphHref(message);

  const [likes, setLikes] = useState(0);
  const [dislikes, setDislikes] = useState(0);
  const [userReaction, setUserReaction] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);

  const handleReaction = useCallback(
    async (reaction: "like" | "dislike") => {
      if (!user) return;
      try {
        const result = await authApi.addReaction(message.event_id, reaction);
        if (result.status === "removed") {
          if (reaction === "like") setLikes((p) => Math.max(0, p - 1));
          else setDislikes((p) => Math.max(0, p - 1));
          setUserReaction(null);
        } else if (result.status === "changed") {
          if (reaction === "like") {
            setLikes((p) => p + 1);
            setDislikes((p) => Math.max(0, p - 1));
          } else {
            setDislikes((p) => p + 1);
            setLikes((p) => Math.max(0, p - 1));
          }
          setUserReaction(reaction);
        } else {
          if (reaction === "like") setLikes((p) => p + 1);
          else setDislikes((p) => p + 1);
          setUserReaction(reaction);
        }
      } catch {
        /* fail silently */
      }
    },
    [user, message.event_id],
  );

  return (
    <>
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: index * 0.03, duration: 0.4, ease: [0.4, 0, 0.2, 1] }}
        whileHover={{ scale: 1.005 }}
        className="bg-card rounded-xl border border-border p-5 transition-all duration-200 hover:shadow-lg hover:shadow-black/5"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Clock className="w-3.5 h-3.5" />
            <span>{format(parseISO(message.date), "HH:mm")}</span>
            <span className="font-semibold text-foreground">{message.channel}</span>
          </div>
          <div className="flex items-center gap-2">
            {sourceUrl && (
              <a
                href={sourceUrl}
                target="_blank"
                rel="noreferrer"
                className="flex h-7 w-7 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                title="Open in Telegram"
                aria-label="Open in Telegram"
              >
                <ExternalLink className="w-3.5 h-3.5" />
              </a>
            )}
            {graphUrl && (
              <Link
                href={graphUrl}
                onClick={() => setIsDemo(false)}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                title="Show in graph"
                aria-label="Show in graph"
              >
                <Network className="w-3.5 h-3.5" />
              </Link>
            )}
            {isAdmin && (
              <button
                onClick={() => setEditOpen(true)}
                className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
                title="Редактировать"
              >
                <Pencil className="w-3.5 h-3.5" />
              </button>
            )}
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full" style={{ backgroundColor: sentColor }} />
              <span className="text-xs font-medium" style={{ color: sentColor }}>{sentLbl}</span>
            </div>
          </div>
        </div>

        <p className="mt-3 text-sm text-foreground leading-relaxed line-clamp-3">{message.text}</p>

        <div className="mt-3 flex items-center justify-between">
          <div className="flex items-center gap-2 flex-wrap">
            {message.topic_label && (
              <Link href={`/topics/${message.cluster_id}`}>
                <Badge variant="topic">{message.topic_label}</Badge>
              </Link>
            )}
            {message.entities?.slice(0, 3).map((e) => (
              <Link key={e.id} href={entityHref(e.id)}>
                <Badge variant="entity" color={entityTypeColor(e.type)}>{e.text}</Badge>
              </Link>
            ))}
            {message.source_status && (
              <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <SourceStatusBadge status={message.source_status} className="px-1.5 py-0.5" />
                {message.source_channel && <span>via {message.source_channel}</span>}
              </div>
            )}
          </div>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <button
              onClick={() => handleReaction("like")}
              className={`flex items-center gap-1 px-1.5 py-0.5 rounded transition-colors ${
                userReaction === "like"
                  ? "text-positive bg-positive/10"
                  : "hover:text-positive"
              }`}
            >
              <ThumbsUp className="w-3.5 h-3.5" />
              {likes > 0 && <span>{likes}</span>}
            </button>
            <button
              onClick={() => handleReaction("dislike")}
              className={`flex items-center gap-1 px-1.5 py-0.5 rounded transition-colors ${
                userReaction === "dislike"
                  ? "text-negative bg-negative/10"
                  : "hover:text-negative"
              }`}
            >
              <ThumbsDown className="w-3.5 h-3.5" />
              {dislikes > 0 && <span>{dislikes}</span>}
            </button>
            <span className="flex items-center gap-1">
              <Eye className="w-3.5 h-3.5" />
              {formatNumber(message.views)}
            </span>
            <span className="flex items-center gap-1">
              <Forward className="w-3.5 h-3.5" />
              {formatNumber(message.forwards)}
            </span>
          </div>
        </div>
      </motion.div>

      {isAdmin && (
        <MessageEditModal
          message={message}
          open={editOpen}
          onClose={() => setEditOpen(false)}
          onSaved={() => {}}
        />
      )}
    </>
  );
}
