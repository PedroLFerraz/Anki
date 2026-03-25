import { useState } from 'react';
import { useGenerate, useGenerateFromArtist, useUpdateCardStatus } from '../api/hooks';
import CardStatusBadge from '../components/cards/CardStatusBadge';
import type { GeneratedCard } from '../api/types';

type Mode = 'artist' | 'topic';

export default function GeneratePage() {
  const [mode, setMode] = useState<Mode>('artist');
  const [artistName, setArtistName] = useState('');
  const [topic, setTopic] = useState('');
  const [count, setCount] = useState(5);
  const [elapsed, setElapsed] = useState(0);

  const artistMut = useGenerateFromArtist();
  const topicMut = useGenerate();
  const updateStatus = useUpdateCardStatus();

  const isPending = artistMut.isPending || topicMut.isPending;
  const result = mode === 'artist' ? artistMut.data : topicMut.data;
  const error = mode === 'artist' ? artistMut.error : topicMut.error;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (mode === 'artist') {
      artistMut.mutate({ artist_name: artistName, deck_type: 'artwork', limit: 0 });
    } else {
      topicMut.mutate({ topic, count, deck_type: 'artwork' });
    }

    // Elapsed timer
    setElapsed(0);
    const start = Date.now();
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000));
    }, 1000);
    const checkDone = setInterval(() => {
      if (!artistMut.isPending && !topicMut.isPending) {
        clearInterval(interval);
        clearInterval(checkDone);
      }
    }, 500);
  };

  const handleCardAction = (card: GeneratedCard, status: string) => {
    updateStatus.mutate({ cardId: card.id, status });
  };

  return (
    <div className="p-6 max-w-3xl">
      <h2 className="text-xl font-bold mb-4">Generate Cards</h2>

      {/* Mode toggle */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setMode('artist')}
          className={`px-3 py-1.5 rounded text-sm ${mode === 'artist' ? 'bg-gray-800 text-white' : 'bg-gray-200'}`}
        >
          Artist Lookup (Wikidata)
        </button>
        <button
          onClick={() => setMode('topic')}
          className={`px-3 py-1.5 rounded text-sm ${mode === 'topic' ? 'bg-gray-800 text-white' : 'bg-gray-200'}`}
        >
          Browse by Topic (Wikidata)
        </button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-3 mb-6">
        {mode === 'artist' ? (
          <div>
            <label className="block text-sm font-medium mb-1">Artist Name</label>
            <input
              type="text"
              value={artistName}
              onChange={(e) => setArtistName(e.target.value)}
              placeholder="e.g. Claude Monet"
              className="w-full border rounded px-3 py-2 text-sm"
              required
              disabled={isPending}
            />
            <p className="text-xs text-gray-400 mt-1">
              Uses Wikidata to find real paintings. Use the artist's full name as on Wikipedia.
            </p>
          </div>
        ) : (
          <>
            <div>
              <label className="block text-sm font-medium mb-1">Topic</label>
              <input
                type="text"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="e.g. Impressionism, Louvre, 1800s"
                className="w-full border rounded px-3 py-2 text-sm"
                required
                disabled={isPending}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Number of cards</label>
              <input
                type="number"
                value={count}
                onChange={(e) => setCount(Number(e.target.value))}
                min={1}
                max={50}
                className="w-24 border rounded px-3 py-2 text-sm"
                disabled={isPending}
              />
            </div>
          </>
        )}

        <button
          type="submit"
          disabled={isPending}
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50"
        >
          {isPending ? 'Searching...' : mode === 'artist' ? 'Look Up Paintings' : 'Search Artworks'}
        </button>
      </form>

      {/* Loading state */}
      {isPending && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
          <div className="flex items-center gap-3">
            <div className="animate-spin w-5 h-5 border-2 border-blue-600 border-t-transparent rounded-full" />
            <div>
              <p className="text-sm font-medium">
                Querying Wikidata...
              </p>
              <p className="text-xs text-gray-500">
                {elapsed}s elapsed
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
          <p className="text-sm text-red-700">{error.message}</p>
        </div>
      )}

      {/* Results */}
      {result && !isPending && (
        <div>
          {result.error && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-4">
              <p className="text-sm text-yellow-700">{result.error}</p>
            </div>
          )}

          {result.message && (
            <p className="text-sm text-gray-500 mb-4">{result.message}</p>
          )}

          {result.total_found !== undefined && (
            <p className="text-sm text-gray-500 mb-3">
              Found {result.total_found} artworks — {result.skipped} already in deck, {result.new || result.cards.length} new.
            </p>
          )}

          {result.persona && (
            <p className="text-sm text-gray-500 mb-3">Persona: {result.persona}</p>
          )}

          {result.cards.length > 0 && (
            <div className="space-y-3">
              <h3 className="font-medium text-sm">
                {result.cards.length} cards generated:
              </h3>
              {result.cards.map((card) => (
                <div key={card.id} className="border rounded-lg p-3 bg-white">
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="font-medium text-sm">{card.fields.Title || '(untitled)'}</p>
                      {card.fields.Artist && (
                        <p className="text-xs text-gray-500">{card.fields.Artist}</p>
                      )}
                      {card.fields.Date && (
                        <p className="text-xs text-gray-400">{card.fields.Date}</p>
                      )}
                      {card.fields.Medium && (
                        <p className="text-xs text-gray-400">{card.fields.Medium}</p>
                      )}
                      {card.fields['Permanent Location'] && (
                        <p className="text-xs text-gray-400">{card.fields['Permanent Location']}</p>
                      )}
                      {card.has_free_image !== undefined && (
                        <p className="text-xs text-gray-400 mt-1">
                          {card.has_free_image ? 'Free image available' : 'No free image (copyrighted)'}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <CardStatusBadge status={card.status} />
                      {card.status === 'GENERATED' && (
                        <>
                          <button
                            onClick={() => handleCardAction(card, 'ACCEPTED')}
                            className="text-xs px-2 py-1 bg-green-600 text-white rounded"
                          >
                            Accept
                          </button>
                          <button
                            onClick={() => handleCardAction(card, 'REJECTED')}
                            className="text-xs px-2 py-1 bg-red-600 text-white rounded"
                          >
                            Reject
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                  {card.duplicate_reason && (
                    <p className="text-xs text-yellow-600 mt-1">Duplicate: {card.duplicate_reason}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
