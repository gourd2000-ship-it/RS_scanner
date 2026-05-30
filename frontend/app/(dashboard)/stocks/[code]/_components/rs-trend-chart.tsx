'use client';

import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import type { RsScoreItem } from '@/types/api';

interface RsTrendChartProps {
  data: RsScoreItem[];
  loading?: boolean;
}

export function RsTrendChart({ data, loading }: RsTrendChartProps) {
  const option = useMemo<EChartsOption>(() => {
    if (data.length === 0) {
      return {};
    }

    // 날짜 오름차순 정렬
    const sortedData = [...data].sort(
      (a, b) => new Date(a.trade_date).getTime() - new Date(b.trade_date).getTime()
    );

    const dates = sortedData.map((item) => item.trade_date);
    const rsRatings = sortedData.map((item) => item.rs_rating);
    const ranks = sortedData.map((item) => item.rank_in_market);

    return {
      animation: true,
      legend: {
        data: ['RS Rating', '시장 내 순위'],
        left: 'center',
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: {
          type: 'cross',
        },
        formatter: (params: any) => {
          const dataIndex = params[0].dataIndex;
          const item = sortedData[dataIndex];

          return `
            <div style="font-weight: bold; margin-bottom: 4px;">${item.trade_date}</div>
            <div>RS Rating: <span style="color: #3b82f6; font-weight: bold;">${item.rs_rating}</span></div>
            <div>시장 내 순위: ${item.rank_in_market}위</div>
            <div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid #e5e7eb;">
              <div>3M 상대수익률: ${(Number(item.return_3m) * 100).toFixed(2)}%</div>
              <div>6M 상대수익률: ${(Number(item.return_6m) * 100).toFixed(2)}%</div>
              <div>12M 상대수익률: ${(Number(item.return_12m) * 100).toFixed(2)}%</div>
            </div>
          `;
        },
      },
      grid: {
        left: '10%',
        right: '10%',
        top: '15%',
        bottom: '15%',
      },
      xAxis: {
        type: 'category',
        data: dates,
        boundaryGap: false,
      },
      yAxis: [
        {
          type: 'value',
          name: 'RS Rating',
          min: 0,
          max: 100,
          position: 'left',
          axisLabel: {
            formatter: '{value}',
          },
          axisLine: {
            show: true,
            lineStyle: {
              color: '#3b82f6',
            },
          },
        },
        {
          type: 'value',
          name: '순위',
          inverse: true,
          position: 'right',
          axisLabel: {
            formatter: '{value}위',
          },
          axisLine: {
            show: true,
            lineStyle: {
              color: '#10b981',
            },
          },
        },
      ],
      dataZoom: [
        {
          type: 'inside',
          start: 0,
          end: 100,
        },
        {
          show: true,
          type: 'slider',
          bottom: '5%',
          start: 0,
          end: 100,
        },
      ],
      series: [
        {
          name: 'RS Rating',
          type: 'line',
          data: rsRatings,
          smooth: true,
          symbol: 'circle',
          symbolSize: 6,
          lineStyle: {
            width: 3,
            color: '#3b82f6',
          },
          itemStyle: {
            color: '#3b82f6',
          },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                {
                  offset: 0,
                  color: 'rgba(59, 130, 246, 0.3)',
                },
                {
                  offset: 1,
                  color: 'rgba(59, 130, 246, 0.05)',
                },
              ],
            },
          },
          markLine: {
            silent: true,
            lineStyle: {
              color: '#ef4444',
              type: 'dashed',
            },
            data: [
              {
                yAxis: 90,
                label: {
                  formatter: 'RS 90',
                  position: 'end',
                },
              },
              {
                yAxis: 80,
                label: {
                  formatter: 'RS 80',
                  position: 'end',
                },
              },
            ],
          },
        },
        {
          name: '시장 내 순위',
          type: 'line',
          yAxisIndex: 1,
          data: ranks,
          smooth: true,
          symbol: 'circle',
          symbolSize: 4,
          lineStyle: {
            width: 2,
            color: '#10b981',
          },
          itemStyle: {
            color: '#10b981',
          },
        },
      ],
    };
  }, [data]);

  if (loading) {
    return (
      <div className="h-64 flex items-center justify-center bg-gray-50 rounded">
        <p className="text-gray-500">차트를 불러오는 중...</p>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="h-64 flex items-center justify-center bg-gray-50 rounded">
        <p className="text-gray-500">RS 데이터가 없습니다</p>
      </div>
    );
  }

  return (
    <ReactECharts
      option={option}
      style={{ height: '400px', width: '100%' }}
      opts={{ renderer: 'canvas' }}
    />
  );
}
