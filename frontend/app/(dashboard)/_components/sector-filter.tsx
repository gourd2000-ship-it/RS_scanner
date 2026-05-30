'use client';

import { Button } from '@/components/ui/button';

const SECTORS = [
  { id: 'all', label: '전체', count: null },
  { id: 'semiconductor', label: '반도체', count: 94 },
  { id: 'auto', label: '자동차', count: 93 },
  { id: 'energy', label: '전력/에너지', count: 88 },
  { id: 'machinery', label: '기계', count: 88 },
  { id: 'battery', label: '2차전지', count: 87 },
  { id: 'infra', label: '인프라', count: 86 },
  { id: 'consumer', label: '소비재', count: 81 },
  { id: 'finance', label: '금융', count: 81 },
  { id: 'it', label: 'IT/클라우드', count: 80 },
  { id: 'defense', label: '방산', count: 79 },
  { id: 'chemicals', label: '화학/소재', count: 74 },
  { id: 'shipping', label: '조선/해운', count: 73 },
  { id: 'bio', label: '바이오', count: 66 },
];

interface SectorFilterProps {
  selectedSector: string;
  onSectorChange: (sectorId: string) => void;
}

export function SectorFilter({ selectedSector, onSectorChange }: SectorFilterProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {SECTORS.map((sector) => (
        <Button
          key={sector.id}
          variant="outline"
          size="sm"
          active={selectedSector === sector.id}
          onClick={() => onSectorChange(sector.id)}
          className="gap-1"
        >
          {sector.count !== null && (
            <span
              className={`w-2 h-2 rounded-full ${
                sector.count >= 90 ? 'bg-red-500' : sector.count >= 80 ? 'bg-orange-500' : 'bg-gray-400'
              }`}
            />
          )}
          <span>{sector.label}</span>
          {sector.count !== null && (
            <span className="text-gray-500">{sector.count}</span>
          )}
        </Button>
      ))}
    </div>
  );
}
