const colors: Record<string, string> = {
  GENERATED: 'bg-blue-100 text-blue-800',
  ACCEPTED: 'bg-green-100 text-green-800',
  REJECTED: 'bg-red-100 text-red-800',
  EXPORTED: 'bg-purple-100 text-purple-800',
  DUPLICATE: 'bg-yellow-100 text-yellow-800',
};

export default function CardStatusBadge({ status }: { status: string }) {
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded ${colors[status] || 'bg-gray-100 text-gray-800'}`}>
      {status}
    </span>
  );
}
