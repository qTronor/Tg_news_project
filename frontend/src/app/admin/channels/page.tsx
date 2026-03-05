"use client";

import { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import { useTranslation } from "@/lib/i18n";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/components/auth/auth-provider";
import { authApi } from "@/lib/auth";
import { Radio, Eye, EyeOff, Loader2, Plus, Search } from "lucide-react";

interface Channel {
  channel_name: string;
  is_visible: boolean;
  updated_at: string | null;
}

export default function AdminChannelsPage() {
  const { t } = useTranslation();
  const { isAdmin } = useAuth();
  const [channels, setChannels] = useState<Channel[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [toggling, setToggling] = useState<string | null>(null);
  const [newChannel, setNewChannel] = useState("");
  const [adding, setAdding] = useState(false);

  const fetchChannels = useCallback(async () => {
    try {
      const data = await authApi.getChannels();
      setChannels(data);
    } catch {
      /* handle error */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isAdmin) fetchChannels();
  }, [isAdmin, fetchChannels]);

  const toggleChannel = async (channelName: string, visible: boolean) => {
    setToggling(channelName);
    try {
      await authApi.setChannelVisibility(channelName, visible);
      setChannels((prev) =>
        prev.map((c) =>
          c.channel_name === channelName ? { ...c, is_visible: visible } : c,
        ),
      );
    } catch {
      /* handle error */
    } finally {
      setToggling(null);
    }
  };

  const addChannel = async () => {
    if (!newChannel.trim()) return;
    setAdding(true);
    try {
      await authApi.setChannelVisibility(newChannel.trim(), true);
      setChannels((prev) => [
        ...prev,
        { channel_name: newChannel.trim(), is_visible: true, updated_at: null },
      ]);
      setNewChannel("");
    } catch {
      /* handle error */
    } finally {
      setAdding(false);
    }
  };

  if (!isAdmin) {
    return (
      <>
        <Header title={t("common.accessDenied")} />
        <PageTransition>
          <div className="flex items-center justify-center min-h-[60vh] text-muted-foreground">
            {t("admin.channels.forbidden")}
          </div>
        </PageTransition>
      </>
    );
  }

  const filtered = channels.filter((c) =>
    c.channel_name.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <>
      <Header title={t("admin.channels.title")} />
      <PageTransition>
        <div className="p-6 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Radio className="w-5 h-5" />
                {t("admin.channels.telegram")}
              </CardTitle>
            </CardHeader>
            <div className="p-5 space-y-4">
              <div className="flex gap-3">
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder={t("admin.channels.search")}
                    className="w-full pl-10 pr-4 py-2.5 bg-muted rounded-lg border border-border text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={newChannel}
                    onChange={(e) => setNewChannel(e.target.value)}
                    placeholder={t("admin.channels.newChannel")}
                    onKeyDown={(e) => e.key === "Enter" && addChannel()}
                    className="px-3 py-2.5 bg-muted rounded-lg border border-border text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 w-48"
                  />
                  <button
                    onClick={addChannel}
                    disabled={adding || !newChannel.trim()}
                    className="flex items-center gap-1.5 px-3 py-2.5 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-all"
                  >
                    {adding ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Plus className="w-4 h-4" />
                    )}
                    {t("admin.channels.add")}
                  </button>
                </div>
              </div>

              {loading ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="w-6 h-6 text-primary animate-spin" />
                </div>
              ) : (
                <div className="space-y-2">
                  {filtered.map((channel, i) => (
                    <motion.div
                      key={channel.channel_name}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.02 }}
                      className="flex items-center justify-between p-3 rounded-lg bg-muted/50 hover:bg-muted transition-colors"
                    >
                      <div className="flex items-center gap-3">
                        <div
                          className={`w-2 h-2 rounded-full ${
                            channel.is_visible ? "bg-positive" : "bg-negative"
                          }`}
                        />
                        <span className="text-sm font-medium text-foreground">
                          {channel.channel_name}
                        </span>
                      </div>
                      <button
                        onClick={() =>
                          toggleChannel(channel.channel_name, !channel.is_visible)
                        }
                        disabled={toggling === channel.channel_name}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                          channel.is_visible
                            ? "bg-positive/10 text-positive border border-positive/20 hover:bg-positive/20"
                            : "bg-negative/10 text-negative border border-negative/20 hover:bg-negative/20"
                        }`}
                      >
                        {toggling === channel.channel_name ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : channel.is_visible ? (
                          <Eye className="w-3.5 h-3.5" />
                        ) : (
                          <EyeOff className="w-3.5 h-3.5" />
                        )}
                        {channel.is_visible ? t("admin.channels.visible") : t("admin.channels.hidden")}
                      </button>
                    </motion.div>
                  ))}
                  {filtered.length === 0 && (
                    <p className="text-center py-8 text-sm text-muted-foreground">
                      {t("admin.channels.notFound")}
                    </p>
                  )}
                </div>
              )}
            </div>
          </Card>
        </div>
      </PageTransition>
    </>
  );
}
