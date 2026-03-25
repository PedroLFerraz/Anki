import type { Card } from '../../api/types';
import CardStatusBadge from './CardStatusBadge';

interface Props {
  card: Card;
  selected: boolean;
  onToggle: () => void;
  onAction: (status: string) => void;
  onFetchMedia: () => void;
}

export default function CardItem({ card, selected, onToggle, onAction, onFetchMedia }: Props) {
  const { fields } = card;
  const title = fields.Title || fields.Topic || '(untitled)';
  const artist = fields.Artist || '';
  const imageFile = card.image_filename;

  return (
    <div className={`border rounded-lg overflow-hidden bg-white shadow-sm ${selected ? 'ring-2 ring-blue-500' : ''}`}>
      {/* Image */}
      <div className="aspect-square bg-gray-100 flex items-center justify-center overflow-hidden">
        {imageFile ? (
          <img src={`/media/${imageFile}`} alt={title} className="w-full h-full object-cover" />
        ) : (
          <span className="text-gray-400 text-sm">No image</span>
        )}
      </div>

      {/* Info */}
      <div className="p-3">
        <div className="flex items-start justify-between gap-2 mb-1">
          <h3 className="font-medium text-sm leading-tight line-clamp-2">{title}</h3>
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            className="mt-0.5 shrink-0"
          />
        </div>
        {artist && <p className="text-xs text-gray-500 mb-1">{artist}</p>}
        {fields.Date && <p className="text-xs text-gray-400">{fields.Date}</p>}

        <div className="flex items-center gap-2 mt-2">
          <CardStatusBadge status={card.status} />
        </div>

        {/* Actions — imported cards are display-only */}
        {card.status !== 'IMPORTED' && (
          <div className="flex gap-1 mt-2">
            {card.status === 'GENERATED' && (
              <>
                <button
                  onClick={() => onAction('ACCEPTED')}
                  className="text-xs px-2 py-1 bg-green-600 text-white rounded hover:bg-green-700"
                >
                  Accept
                </button>
                <button
                  onClick={() => onAction('REJECTED')}
                  className="text-xs px-2 py-1 bg-red-600 text-white rounded hover:bg-red-700"
                >
                  Reject
                </button>
              </>
            )}
            {!card.image_filename && card.status !== 'REJECTED' && (
              <button
                onClick={onFetchMedia}
                className="text-xs px-2 py-1 bg-gray-600 text-white rounded hover:bg-gray-700"
              >
                Fetch Image
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
