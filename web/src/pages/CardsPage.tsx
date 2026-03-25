import { useState, useCallback } from 'react';
import { useCards, useUpdateCardStatus, useFetchMedia, useExport } from '../api/hooks';
import CardItem from '../components/cards/CardItem';

const STATUS_FILTERS = ['ALL', 'GENERATED', 'ACCEPTED', 'REJECTED', 'EXPORTED', 'DUPLICATE', 'IMPORTED'];

export default function CardsPage() {
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const { data: cards, isLoading } = useCards(
    statusFilter === 'ALL' ? undefined : { status: statusFilter }
  );
  const updateStatus = useUpdateCardStatus();
  const fetchMedia = useFetchMedia();
  const exportMut = useExport();

  const toggleSelect = useCallback((id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectAll = () => {
    if (!cards) return;
    setSelected(new Set(cards.map((c) => c.id)));
  };
  const selectNone = () => setSelected(new Set());

  const bulkAction = async (status: string) => {
    for (const id of selected) {
      await updateStatus.mutateAsync({ cardId: id, status });
    }
    setSelected(new Set());
  };

  const handleExport = async () => {
    if (selected.size === 0) return;
    const blob = await exportMut.mutateAsync({
      card_ids: Array.from(selected),
      deck_name: 'Great Works of Art',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'Great Works of Art.apkg';
    a.click();
    URL.revokeObjectURL(url);
  };

  if (isLoading) return <p className="p-6 text-gray-500">Loading cards...</p>;

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold">Cards ({cards?.length || 0})</h2>

        <div className="flex gap-2 items-center">
          {/* Status filter */}
          {STATUS_FILTERS.map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`text-xs px-2 py-1 rounded ${
                statusFilter === s ? 'bg-gray-800 text-white' : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Bulk actions */}
      {selected.size > 0 && (
        <div className="flex gap-2 items-center mb-4 p-3 bg-blue-50 rounded-lg">
          <span className="text-sm font-medium">{selected.size} selected</span>
          <button onClick={() => bulkAction('ACCEPTED')} className="text-xs px-2 py-1 bg-green-600 text-white rounded">
            Accept
          </button>
          <button onClick={() => bulkAction('REJECTED')} className="text-xs px-2 py-1 bg-red-600 text-white rounded">
            Reject
          </button>
          <button onClick={handleExport} disabled={exportMut.isPending} className="text-xs px-2 py-1 bg-purple-600 text-white rounded">
            {exportMut.isPending ? 'Exporting...' : 'Export .apkg'}
          </button>
          <button onClick={selectNone} className="text-xs px-2 py-1 bg-gray-400 text-white rounded ml-auto">
            Deselect
          </button>
        </div>
      )}

      {/* Select all */}
      <div className="flex gap-2 mb-4">
        <button onClick={selectAll} className="text-xs text-blue-600 hover:underline">Select all</button>
        {selected.size > 0 && (
          <button onClick={selectNone} className="text-xs text-gray-500 hover:underline">Clear</button>
        )}
      </div>

      {/* Card grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
        {cards?.map((card) => (
          <CardItem
            key={card.id}
            card={card}
            selected={selected.has(card.id)}
            onToggle={() => toggleSelect(card.id)}
            onAction={(status) => updateStatus.mutate({ cardId: card.id, status })}
            onFetchMedia={() => fetchMedia.mutate(card.id)}
          />
        ))}
      </div>

      {cards?.length === 0 && (
        <p className="text-gray-400 text-center py-12">No cards found.</p>
      )}
    </div>
  );
}
