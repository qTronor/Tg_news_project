'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { getPaper, triggerPaperSummarize } from '@/lib/api';
import type { PaperDetail } from '@/types';

const SOURCE_TYPE_LABELS: Record<string, string> = {
  arxiv: 'arXiv', openreview: 'OpenReview', doi: 'DOI',
  pdf_url: 'PDF', telegram_file: 'Telegram PDF', webpage: 'Webpage',
};

const STATUS_COLORS: Record<string, string> = {
  parsed: 'bg-green-100 text-green-800',
  partial: 'bg-yellow-100 text-yellow-800',
  failed: 'bg-red-100 text-red-800',
  detected: 'bg-gray-100 text-gray-700',
  parsing: 'bg-blue-100 text-blue-800',
};

function SectionRow({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null;
  return (
    <div className="py-3 border-b last:border-0">
      <dt className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">{label}</dt>
      <dd className="text-sm text-gray-800 whitespace-pre-wrap">{value}</dd>
    </div>
  );
}

function BadgeList({ label, items }: { label: string; items?: string[] }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="py-3 border-b last:border-0">
      <dt className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">{label}</dt>
      <dd className="flex flex-wrap gap-2">
        {items.map((item, i) => (
          <span key={i} className="bg-gray-100 text-gray-700 text-xs px-2 py-1 rounded-full">{item}</span>
        ))}
      </dd>
    </div>
  );
}

export default function PaperDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [paper, setPaper] = useState<PaperDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [resummaryStatus, setResummaryStatus] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    getPaper(id)
      .then(setPaper)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [id]);

  const handleResummary = async () => {
    if (!id) return;
    setResummaryStatus('loading');
    try {
      const res = await triggerPaperSummarize(id);
      setResummaryStatus(res.status);
    } catch {
      setResummaryStatus('error');
    }
  };

  if (loading) return <div className="p-6 text-gray-500">Загрузка...</div>;
  if (!paper) return <div className="p-6 text-gray-500">Статья не найдена</div>;

  const s = paper.summary?.summary_json;

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <Link href="/papers" className="text-blue-600 text-sm hover:underline mb-4 inline-block">
        ← Все статьи
      </Link>

      <div className="bg-white border rounded-xl p-6 mb-6">
        <div className="flex items-start justify-between gap-4 mb-4">
          <h1 className="text-2xl font-bold text-gray-900">{paper.title || 'Без названия'}</h1>
          <div className="flex gap-2 shrink-0">
            <span className={`text-xs px-2 py-1 rounded-full font-medium ${STATUS_COLORS[paper.parsing_status] || 'bg-gray-100'}`}>
              {paper.parsing_status}
            </span>
            <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-1 rounded-full">
              {SOURCE_TYPE_LABELS[paper.source_type] || paper.source_type}
            </span>
          </div>
        </div>

        {paper.authors.length > 0 && (
          <p className="text-gray-600 mb-3">{paper.authors.join(', ')}</p>
        )}

        <div className="flex flex-wrap gap-4 text-sm text-gray-500 mb-4">
          <span>Канал: <strong>{paper.source_channel}</strong></span>
          <span>Обнаружено: {new Date(paper.detected_at).toLocaleString('ru-RU')}</span>
          {paper.published_at && (
            <span>Опубликовано: {new Date(paper.published_at).toLocaleDateString('ru-RU')}</span>
          )}
        </div>

        {paper.source_url && (
          <a
            href={paper.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 text-sm hover:underline break-all"
          >
            {paper.source_url}
          </a>
        )}
      </div>

      {paper.abstract && (
        <div className="bg-white border rounded-xl p-6 mb-6">
          <h2 className="text-lg font-semibold mb-3">Аннотация</h2>
          <p className="text-sm text-gray-800 whitespace-pre-wrap">{paper.abstract}</p>
        </div>
      )}

      {s && (
        <div className="bg-white border rounded-xl p-6 mb-6">
          <h2 className="text-lg font-semibold mb-4">Структурированный анализ</h2>
          {s.short_summary && (
            <div className="bg-blue-50 rounded-lg p-4 mb-4">
              <p className="text-sm font-medium text-blue-900">{s.short_summary}</p>
            </div>
          )}
          <dl className="divide-y">
            <SectionRow label="Краткое изложение аннотации" value={s.abstract_summary} />
            <SectionRow label="Научная проблема" value={s.research_problem} />
            <SectionRow label="Основной вклад" value={s.main_contribution} />
            <SectionRow label="Метод" value={s.method} />
            <SectionRow label="Эксперименты" value={s.experiments} />
            <SectionRow label="Результаты" value={s.results} />
            <SectionRow label="Ограничения" value={s.limitations} />
            <BadgeList label="Датасеты" items={s.datasets} />
            <BadgeList label="Метрики" items={s.metrics} />
            <BadgeList label="Ключевые слова" items={s.keywords} />
            {s.paper_type && (
              <div className="py-3">
                <dt className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Тип работы</dt>
                <dd>
                  <span className="bg-purple-100 text-purple-700 text-xs px-2 py-1 rounded-full">{s.paper_type}</span>
                </dd>
              </div>
            )}
          </dl>
          <div className="mt-4 pt-4 border-t text-xs text-gray-400">
            Модель: {paper.summary?.model_name} · Версия промпта: {paper.summary?.prompt_version} ·
            Создано: {paper.summary?.created_at ? new Date(paper.summary.created_at).toLocaleString('ru-RU') : '—'}
          </div>
        </div>
      )}

      <div className="flex justify-end">
        <button
          onClick={handleResummary}
          disabled={resummaryStatus === 'loading'}
          className="text-sm bg-gray-100 hover:bg-gray-200 text-gray-700 px-4 py-2 rounded-lg transition-colors disabled:opacity-50"
        >
          {resummaryStatus === 'loading' ? 'Отправка...' : resummaryStatus === 'queued' ? 'В очереди' : 'Перегенерировать summary'}
        </button>
      </div>
    </div>
  );
}
