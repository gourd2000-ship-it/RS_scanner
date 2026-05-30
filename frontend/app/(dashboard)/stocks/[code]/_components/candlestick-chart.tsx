'use client';

import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import type { DailyPriceItem } from '@/types/api';

interface CandlestickChartProps {
  data: DailyPriceItem[];
  loading?: boolean;
}

export function CandlestickChart({ data, loading }: CandlestickChartProps) {
  const option = useMemo<EChartsOption>(() => {
    if (data.length === 0) {
      return {};
    }

    // 날짜 오름차순 정렬 (오래된 것부터)
    const sortedData = [...data].sort(
      (a, b) => new Date(a.trade_date).getTime() - new Date(b.trade_date).getTime()
    );

    // 데이터 변환
    const dates = sortedData.map((item) => item.trade_date);
    const ohlc = sortedData.map((item) => [
      Number(item.open),
      Number(item.close),
      Number(item.low),
      Number(item.high),
    ]);
    const volumes = sortedData.map((item) => item.volume);

    return {
      animation: true,
      legend: {
        data: ['일봉', '거래량'],
        left: 'center',
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: {
          type: 'cross',
        },
        formatter: (params: any) => {
          const param = params[0];
          const dataIndex = param.dataIndex;
          const item = sortedData[dataIndex];

          return `
            <div style="font-weight: bold; margin-bottom: 4px;">${item.trade_date}</div>
            <div>시가: ${Number(item.open).toLocaleString('ko-KR')}원</div>
            <div>고가: ${Number(item.high).toLocaleString('ko-KR')}원</div>
            <div>저가: ${Number(item.low).toLocaleString('ko-KR')}원</div>
            <div>종가: ${Number(item.close).toLocaleString('ko-KR')}원</div>
            <div>거래량: ${item.volume.toLocaleString('ko-KR')}</div>
          `;
        },
      },
      grid: [
        {
          left: '10%',
          right: '8%',
          top: '10%',
          height: '50%',
        },
        {
          left: '10%',
          right: '8%',
          top: '70%',
          height: '16%',
        },
      ],
      xAxis: [
        {
          type: 'category',
          data: dates,
          boundaryGap: true,
          axisLine: { onZero: false },
          splitLine: { show: false },
          min: 'dataMin',
          max: 'dataMax',
        },
        {
          type: 'category',
          gridIndex: 1,
          data: dates,
          boundaryGap: true,
          axisLine: { onZero: false },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: { show: false },
          min: 'dataMin',
          max: 'dataMax',
        },
      ],
      yAxis: [
        {
          scale: true,
          splitArea: {
            show: true,
          },
          axisLabel: {
            formatter: (value: number) => value.toLocaleString('ko-KR'),
          },
        },
        {
          scale: true,
          gridIndex: 1,
          splitNumber: 2,
          axisLabel: { show: false },
          axisLine: { show: false },
          axisTick: { show: false },
          splitLine: { show: false },
        },
      ],
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: [0, 1],
          start: 70,
          end: 100,
        },
        {
          show: true,
          xAxisIndex: [0, 1],
          type: 'slider',
          bottom: '8%',
          start: 70,
          end: 100,
        },
      ],
      series: [
        {
          name: '일봉',
          type: 'candlestick',
          data: ohlc,
          itemStyle: {
            color: '#ef4444',
            color0: '#3b82f6',
            borderColor: '#ef4444',
            borderColor0: '#3b82f6',
          },
        },
        {
          name: '거래량',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes,
          itemStyle: {
            color: (params: any) => {
              const dataIndex = params.dataIndex;
              const item = sortedData[dataIndex];
              return Number(item.close) >= Number(item.open) ? '#ef4444' : '#3b82f6';
            },
          },
        },
      ],
    };
  }, [data]);

  if (loading) {
    return (
      <div className="h-96 flex items-center justify-center bg-gray-50 rounded">
        <p className="text-gray-500">차트를 불러오는 중...</p>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="h-96 flex items-center justify-center bg-gray-50 rounded">
        <p className="text-gray-500">가격 데이터가 없습니다</p>
      </div>
    );
  }

  return (
    <ReactECharts
      option={option}
      style={{ height: '500px', width: '100%' }}
      opts={{ renderer: 'canvas' }}
    />
  );
}
