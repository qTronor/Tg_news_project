"use client";

import { useState } from "react";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useDemoContext } from "@/components/providers";
import { Save, Plus, Trash2, Server, Database, Bell, Palette } from "lucide-react";
import { motion } from "framer-motion";
import { useTheme } from "next-themes";

export default function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const { isDemo, setIsDemo } = useDemoContext();
  const [apiUrl, setApiUrl] = useState("http://localhost:8020");
  const [pollingInterval, setPollingInterval] = useState("15");
  const [channels, setChannels] = useState([
    "РБК", "ТАСС", "Коммерсантъ", "Медуза", "Интерфакс", "Ведомости",
  ]);
  const [newChannel, setNewChannel] = useState("");
  const [notifications, setNotifications] = useState(true);
  const [saved, setSaved] = useState(false);

  const addChannel = () => {
    if (newChannel.trim() && !channels.includes(newChannel.trim())) {
      setChannels([...channels, newChannel.trim()]);
      setNewChannel("");
    }
  };

  const removeChannel = (ch: string) => {
    setChannels(channels.filter(c => c !== ch));
  };

  const handleSave = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <>
      <Header title="Settings" />
      <PageTransition>
        <div className="p-6 space-y-6 max-w-3xl">
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Server className="w-4 h-4 text-primary" />
                <CardTitle>Connection</CardTitle>
              </div>
              <CardDescription>Configure the analytics API endpoint</CardDescription>
            </CardHeader>
            <div className="space-y-4">
              <div>
                <label className="text-xs font-medium text-muted-foreground">API Base URL</label>
                <input
                  type="text"
                  value={apiUrl}
                  onChange={e => setApiUrl(e.target.value)}
                  className="mt-1 w-full px-3 py-2 bg-muted rounded-lg text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/30 transition-all font-mono"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground">Polling Interval (seconds)</label>
                <input
                  type="number"
                  value={pollingInterval}
                  onChange={e => setPollingInterval(e.target.value)}
                  className="mt-1 w-32 px-3 py-2 bg-muted rounded-lg text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/30 transition-all"
                />
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-foreground">Demo Mode</p>
                  <p className="text-xs text-muted-foreground">Use mock data instead of live API</p>
                </div>
                <button
                  onClick={() => setIsDemo(!isDemo)}
                  className={`relative w-11 h-6 rounded-full transition-colors duration-300 ${isDemo ? "bg-amber-500" : "bg-positive"}`}
                >
                  <motion.div
                    animate={{ x: isDemo ? 2 : 22 }}
                    transition={{ type: "spring", stiffness: 500, damping: 30 }}
                    className="absolute top-1 w-4 h-4 bg-white rounded-full shadow-sm"
                  />
                </button>
              </div>
            </div>
          </Card>

          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Database className="w-4 h-4 text-primary" />
                <CardTitle>Watched Channels</CardTitle>
              </div>
              <CardDescription>Manage the Telegram channels being monitored</CardDescription>
            </CardHeader>
            <div className="space-y-3">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={newChannel}
                  onChange={e => setNewChannel(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && addChannel()}
                  placeholder="Add channel name..."
                  className="flex-1 px-3 py-2 bg-muted rounded-lg text-sm text-foreground placeholder:text-muted-foreground outline-none focus:ring-2 focus:ring-primary/30 transition-all"
                />
                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={addChannel}
                  className="px-3 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium"
                >
                  <Plus className="w-4 h-4" />
                </motion.button>
              </div>
              <div className="flex flex-wrap gap-2">
                {channels.map(ch => (
                  <motion.div
                    key={ch}
                    initial={{ opacity: 0, scale: 0.8 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.8 }}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-muted rounded-lg text-sm text-foreground"
                  >
                    {ch}
                    <button onClick={() => removeChannel(ch)} className="text-muted-foreground hover:text-destructive transition-colors">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </motion.div>
                ))}
              </div>
            </div>
          </Card>

          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Bell className="w-4 h-4 text-primary" />
                <CardTitle>Notifications</CardTitle>
              </div>
              <CardDescription>Alert settings for new topic detection</CardDescription>
            </CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-foreground">New Topic Alerts</p>
                <p className="text-xs text-muted-foreground">Get notified when a new topic cluster is detected</p>
              </div>
              <button
                onClick={() => setNotifications(!notifications)}
                className={`relative w-11 h-6 rounded-full transition-colors duration-300 ${notifications ? "bg-primary" : "bg-muted"}`}
              >
                <motion.div
                  animate={{ x: notifications ? 22 : 2 }}
                  transition={{ type: "spring", stiffness: 500, damping: 30 }}
                  className="absolute top-1 w-4 h-4 bg-white rounded-full shadow-sm"
                />
              </button>
            </div>
          </Card>

          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Palette className="w-4 h-4 text-primary" />
                <CardTitle>Appearance</CardTitle>
              </div>
            </CardHeader>
            <div className="flex gap-3">
              {["light", "dark", "system"].map(t => (
                <button
                  key={t}
                  onClick={() => setTheme(t)}
                  className={`px-4 py-2 rounded-lg text-sm font-medium capitalize transition-all duration-200 ${
                    theme === t ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </Card>

          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={handleSave}
            className={`flex items-center gap-2 px-6 py-3 rounded-xl text-sm font-semibold transition-all duration-300 ${
              saved
                ? "bg-positive text-white"
                : "bg-primary text-primary-foreground hover:brightness-110"
            }`}
          >
            <Save className="w-4 h-4" />
            {saved ? "Saved!" : "Save Settings"}
          </motion.button>
        </div>
      </PageTransition>
    </>
  );
}
