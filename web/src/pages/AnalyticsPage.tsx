import { useAnalytics } from '../api/hooks';

export default function AnalyticsPage() {
  const { data: rows, isLoading } = useAnalytics();

  if (isLoading) return <p className="p-6 text-gray-500">Loading...</p>;

  const totalCards = rows?.reduce((s, r) => s + r.total_cards, 0) || 0;
  const totalAccepted = rows?.reduce((s, r) => s + r.accepted, 0) || 0;
  const totalRejected = rows?.reduce((s, r) => s + r.rejected, 0) || 0;

  return (
    <div className="p-6 max-w-4xl">
      <h2 className="text-xl font-bold mb-4">Analytics</h2>

      {/* Summary */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="bg-white border rounded-lg p-4 text-center">
          <p className="text-2xl font-bold">{totalCards}</p>
          <p className="text-xs text-gray-500">Total Cards</p>
        </div>
        <div className="bg-white border rounded-lg p-4 text-center">
          <p className="text-2xl font-bold text-green-600">{totalAccepted}</p>
          <p className="text-xs text-gray-500">Accepted</p>
        </div>
        <div className="bg-white border rounded-lg p-4 text-center">
          <p className="text-2xl font-bold text-red-600">{totalRejected}</p>
          <p className="text-xs text-gray-500">Rejected</p>
        </div>
      </div>

      {/* Per-topic breakdown */}
      {rows && rows.length > 0 && (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b text-left">
              <th className="py-2 font-medium">Topic</th>
              <th className="py-2 font-medium">Deck Type</th>
              <th className="py-2 font-medium text-right">Total</th>
              <th className="py-2 font-medium text-right">Accepted</th>
              <th className="py-2 font-medium text-right">Rejected</th>
              <th className="py-2 font-medium text-right">Rate</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b">
                <td className="py-2">{r.topic || '(none)'}</td>
                <td className="py-2 text-gray-500">{r.deck_type}</td>
                <td className="py-2 text-right">{r.total_cards}</td>
                <td className="py-2 text-right text-green-600">{r.accepted}</td>
                <td className="py-2 text-right text-red-600">{r.rejected}</td>
                <td className="py-2 text-right">
                  {r.total_cards > 0
                    ? `${Math.round((r.accepted / r.total_cards) * 100)}%`
                    : '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
