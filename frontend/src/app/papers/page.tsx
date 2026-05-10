'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { getPapers } from '@/lib/api';
import type { ScientificPaper } from '@/types';

const SOURCE_TYPE_LABELS: Record<string, string> = {
  arxiv: 'arXiv',
  openreview: 'OpenReview',
  doi: 'DOI',
  pdf_url: 'PDF',
  telegram_file: 'Telegram PDF',
  webpage: 'Webpage',
};

const STATUS_COLORS: Record<string, string> = {
  parsed: 'bg-green-100 text-green-800',
  partial: 'bg-yellow-100 text-yellow-800',
  failed: 'bg-red-100 text-red-800',
  detected: 'bg-gray-100 text-gray-700',
  parsing: 'bg-blue-100 text-blue-800',
};

export default function PapersPage() {
  const [papers, setPapers] = useState<ScientificPaper[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [sourceType, setSourceType] = useState('');
  const [status, setStatus] = useState('');

  useEffect(() => {
    setLoading(true);
    getPapers({ search: search || undefined, source_type: sourceType || undefined, parsing_status: status || undefined })
      .then(setPapers)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [search, sourceType, status]);

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">Научные статьи</h1>

      <div className="flex flex-wrap gap-3 mb-6">
        <input
          className="border rounded px-3 py-2 text-sm w-64"
          placeholder="Поиск по названию или аннотации..."
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <select
          className="border rounded px-3 py-2 text-sm"
          value={sourceType}
          onChange={e => setSourceType(e.target.value)}
        >
          <option value="">Все типы</option>
          {Object.entries(SOURCE_TYPE_LABELS).map(([v, l]) => (
            <option key={v} value={v}>{l}</option>
          ))}
        </select>
        <select
          className="border rounded px-3 py-2 text-sm"
          value={status}
          onChange={e => setStatus(e.target.value)}
        >
          <option value="">Все статусы</option>
          <option value="parsed">Обработано</option>
          <option value="partial">Частично</option>
          <option value="detected">Обнаружено</option>
          <option value="failed">Ошибка</option>
        </select>
      </div>

      {loading ? (
        <div className="text-gray-500">Загрузка...</div>
      ) : papers.length === 0 ? (
        <div className="text-gray-500">Статьи не найдены</div>
      ) : (
        <div className="space-y-4">
          {papers.map((paper, i) => (
            <motion.div
              key={paper.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.03 }}
              className="border rounded-lg p-4 bg-white hover:shadow-md transition-shadow"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <Link
                    href={`/papers/${paper.id}`}
                    className="text-lg font-semibold text-blue-700 hover:underline line-clamp-2"
                  >
                    {paper.title || 'Без названия'}
                  </Link>
                  {paper.authors.length > 0 && (
                    <p className="text-sm text-gray-600 mt-1">
                      {paper.authors.slice(0, 2).join(', ')}
                      {paper.authors.length > 2 && ` и др.`}
                    </p>
                  )}
                  {paper.short_summary && (
                    <p className="text-sm text-gray-700 mt-2 line-clamp-2">
                      {paper.short_summary}
                    </p>
                  )}
                </div>
                <div className="flex flex-col items-end gap-2 shrink-0">
                  <span className={`text-xs px-2 py-1 rounded-full font-medium ${STATUS_COLORS[paper.parsing_status] || 'bg-gray-100'}`}>
                    {paper.parsing_status}
                  </span>
                  <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-1 rounded-full">
                    {SOURCE_TYPE_LABELS[paper.source_type] || paper.source_type}
                  </span>
                </div>
              </div>
              <div className="mt-3 flex items-center gap-4 text-xs text-gray-500">
                <span>{paper.source_channel}</span>
                <span>{new Date(paper.detected_at).toLocaleDateString('ru-RU')}</span>
                {paper.has_summary && <span className="text-green-600">✓ Summary</span>}
              </div>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
