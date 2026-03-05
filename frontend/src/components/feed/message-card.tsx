"use client";

import { motion } from "framer-motion";
import { Badge } from "@/components/ui/badge";
import { formatNumber, entityTypeColor, sentimentColor, sentimentLabel } from "@/lib/utils";
import type { Message } from "@/types";
import { Eye, Forward, Clock } from "lucide-react";
import { format, parseISO } from "date-fns";
import Link from "next/link";

interface Props {
  message: Message;
  index: number;
}

export function MessageCard({ message, index }: Props) {
  const sentColor = sentimentColor(message.sentiment_score || 0);
  const sentLbl = sentimentLabel(message.sentiment_score || 0);

  return (
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
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: sentColor }} />
          <span className="text-xs font-medium" style={{ color: sentColor }}>{sentLbl}</span>
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
          {message.entities?.slice(0, 3).map(e => (
            <Link key={e.id} href={`/entities/${e.id}`}>
              <Badge variant="entity" color={entityTypeColor(e.type)}>{e.text}</Badge>
            </Link>
          ))}
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1"><Eye className="w-3.5 h-3.5" />{formatNumber(message.views)}</span>
          <span className="flex items-center gap-1"><Forward className="w-3.5 h-3.5" />{formatNumber(message.forwards)}</span>
        </div>
      </div>
    </motion.div>
  );
}
