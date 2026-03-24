import { NavLink } from 'react-router-dom';

const links = [
  { to: '/', label: 'Cards' },
  { to: '/generate', label: 'Generate' },
  { to: '/analytics', label: 'Analytics' },
];

export default function Sidebar() {
  return (
    <nav className="w-56 bg-gray-900 text-gray-300 min-h-screen p-4 flex flex-col gap-1">
      <h1 className="text-lg font-bold text-white mb-6 px-3">Anki Art Cards</h1>
      {links.map((l) => (
        <NavLink
          key={l.to}
          to={l.to}
          className={({ isActive }) =>
            `block px-3 py-2 rounded text-sm ${
              isActive ? 'bg-gray-700 text-white font-medium' : 'hover:bg-gray-800'
            }`
          }
        >
          {l.label}
        </NavLink>
      ))}
    </nav>
  );
}
