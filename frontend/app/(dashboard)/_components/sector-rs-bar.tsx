'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { SectorData } from '@/lib/hooks/use-sector-data';

interface SectorRsBarProps {
  sectors: SectorData[];
  loading?: boolean;
}

export function SectorRsBar({ sectors, loading }: SectorRsBarProps) {
  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-medium flex items-center gap-2">
            한 눈에 보는 섹터RS
            <span className="text-sm text-gray-500 font-normal">ℹ</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          <div className="h-24 bg-gray-100 animate-pulse rounded-lg" />
        </CardContent>
      </Card>
    );
  }

  // 표시할 섹터 수 제한 (상위 15개)
  const displaySectors = sectors.slice(0, 15);

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base font-medium flex items-center gap-2">
          한 눈에 보는 섹터RS
          <span className="text-sm text-gray-500 font-normal">ℹ</span>
          <span className="ml-auto text-sm text-gray-500 font-normal">
            {displaySectors.length}개 섹터
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="relative h-24">
          {/* 배경 그라데이션 바 */}
          <div className="absolute inset-0 flex">
            <div
              className="h-full bg-gradient-to-r from-blue-200 via-yellow-100 to-red-200 rounded-full"
              style={{ width: '100%' }}
            />
          </div>

          {/* 섹터 마커들 */}
          <div className="absolute inset-0">
            {displaySectors.map((sector, index) => {
              // RS 값을 0-100 범위로 조정 (최소 56, 최대 100)
              const position = Math.max(0, Math.min(100, sector.rs));

              return (
                <div
                  key={`${sector.market}-${sector.name}-${index}`}
                  className="absolute group"
                  style={{
                    left: `${position}%`,
                    top: index % 2 === 0 ? '0' : '50%',
                  }}
                >
                  {/* 툴팁 */}
                  <div className="absolute -top-10 left-1/2 -translate-x-1/2 bg-gray-900 text-white text-xs px-2 py-1 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap z-10">
                    {sector.name}: {sector.rs} ({sector.count}개)
                  </div>

                  {/* 시장 뱃지 */}
                  <div
                    className={`mb-1 px-1.5 py-0.5 rounded text-xs font-medium cursor-pointer ${
                      sector.market === 'KOSPI'
                        ? 'bg-blue-100 text-blue-700'
                        : 'bg-purple-100 text-purple-700'
                    }`}
                  >
                    {sector.market === 'KOSPI' ? 'KS' : 'KQ'}
                  </div>
                  {/* 아이콘 */}
                  <div className="text-lg cursor-pointer">{getSectorIcon(sector.name)}</div>
                </div>
              );
            })}
          </div>

          {/* 눈금 */}
          <div className="absolute -bottom-4 left-0 text-xs text-gray-500">약함 0</div>
          <div className="absolute -bottom-4 right-0 text-xs text-gray-500">100 강함</div>
        </div>
      </CardContent>
    </Card>
  );
}

function getSectorIcon(sectorName: string): string {
  const iconMap: Record<string, string> = {
    반도체: '📱',
    자동차: '🚗',
    '전력/에너지': '⚡',
    기계: '⚙️',
    인프라: '🏗️',
    '2차전지': '🔋',
    소비재: '🛒',
    금융: '💰',
    'IT/클라우드': '☁️',
    방산: '🛡️',
    '화학/소재': '⚗️',
    '조선/해운': '🚢',
    바이오: '🧬',
    'K-컨텐츠': '🎬',
    기타: '📊',
  };
  return iconMap[sectorName] || '📊';
}
