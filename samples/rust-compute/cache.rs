use crate::math_engine::{ComputeParams, DataPoint};
use moka::sync::Cache;
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::task::JoinHandle;

#[derive(Debug, Clone)]
pub struct PredictiveCache {
    hot_cache: Arc<Cache<String, Arc<Vec<DataPoint>>>>,
    parameter_history: Arc<tokio::sync::Mutex<VecDeque<ComputeParams>>>,
}

impl PredictiveCache {
    pub fn new() -> Self {
        let cache = Cache::builder()
            .max_capacity(100)
            .time_to_live(Duration::from_secs(900))
            .time_to_idle(Duration::from_secs(300))
            .build();
        
        Self {
            hot_cache: Arc::new(cache),
            parameter_history: Arc::new(tokio::sync::Mutex::new(VecDeque::with_capacity(50))),
        }
    }
    
    pub async fn start_background_computing(
        &self,
        math_engine: Arc<crate::math_engine::MathEngine>,
    ) -> JoinHandle<()> {
        let cache = self.hot_cache.clone();
        let history = self.parameter_history.clone();
        
        let handle = tokio::spawn(async move {
            let mut predictor = ParameterPredictor::new();
            
            loop {
                let predicted_params = {
                    let hist = history.lock().await;
                    predictor.predict_next_parameters(&hist)
                };
                
                for params in predicted_params {
                    let key = Self::generate_cache_key(&params);
                    
                    if !cache.contains_key(&key) {
                        let engine = math_engine.clone();
                        let cache_clone = cache.clone();
                        
                        tokio::task::spawn_blocking(move || {
                            let data = engine.compute(&params);
                            cache_clone.insert(key, Arc::new(data));
                        });
                    }
                }
                
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
        });
        
        handle
    }
    
    pub fn get(&self, params: &ComputeParams) -> Option<Arc<Vec<DataPoint>>> {
        let key = Self::generate_cache_key(params);
        self.hot_cache.get(&key)
    }
    
    pub fn insert(&self, params: &ComputeParams, data: Vec<DataPoint>) {
        let key = Self::generate_cache_key(params);
        self.hot_cache.insert(key, Arc::new(data));
    }
    
    pub async fn record_access(&self, params: ComputeParams) {
        let mut history = self.parameter_history.lock().await;
        history.push_back(params);
        
        if history.len() > 50 {
            history.pop_front();
        }
    }
    
    fn generate_cache_key(params: &ComputeParams) -> String {
        format!(
            "{}_{}_{:.2}_{:.2}_{:.2}_{:.2}_{}_{:.2}_{:.2}",
            params.visualization_type,
            params.points,
            params.sigma,
            params.rho,
            params.beta,
            params.zoom,
            params.iterations,
            params.x_offset,
            params.y_offset
        )
    }
    
    pub fn get_stats(&self) -> CacheStatistics {
        CacheStatistics {
            total_entries: self.hot_cache.entry_count() as usize,
            hit_count: self.hot_cache.weighted_size() as usize,
            estimated_size_mb: (self.hot_cache.weighted_size() * 200) / (1024 * 1024),
        }
    }
    
    pub fn clear(&self) {
        self.hot_cache.invalidate_all();
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CacheStatistics {
    pub total_entries: usize,
    pub hit_count: usize,
    pub estimated_size_mb: u64,
}

struct ParameterPredictor {
    zoom_patterns: Vec<f64>,
    iteration_patterns: Vec<u32>,
    common_offsets: Vec<(f64, f64)>,
}

impl ParameterPredictor {
    fn new() -> Self {
        Self {
            zoom_patterns: vec![0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0],
            iteration_patterns: vec![64, 128, 256, 512, 1024],
            common_offsets: vec![
                (0.0, 0.0),
                (-0.5, 0.0),
                (0.5, 0.0),
                (0.0, -0.5),
                (0.0, 0.5),
                (-0.7, 0.27),
            ],
        }
    }
    
    fn predict_next_parameters(&self, history: &VecDeque<ComputeParams>) -> Vec<ComputeParams> {
        let mut predictions = Vec::new();
        
        if let Some(last_params) = history.back() {
            for &zoom in &self.zoom_patterns {
                if (zoom - last_params.zoom).abs() > 0.01 {
                    let mut params = last_params.clone();
                    params.zoom = zoom;
                    predictions.push(params);
                }
            }
            
            for &iterations in &self.iteration_patterns {
                if iterations != last_params.iterations {
                    let mut params = last_params.clone();
                    params.iterations = iterations;
                    predictions.push(params);
                }
            }
            
            for &(x_off, y_off) in &self.common_offsets {
                if (x_off - last_params.x_offset).abs() > 0.01 
                    || (y_off - last_params.y_offset).abs() > 0.01 {
                    let mut params = last_params.clone();
                    params.x_offset = x_off;
                    params.y_offset = y_off;
                    predictions.push(params);
                }
            }
            
            if history.len() >= 3 {
                let trend = self.analyze_zoom_trend(history);
                if trend.abs() > 0.1 {
                    let mut params = last_params.clone();
                    params.zoom = (last_params.zoom * (1.0 + trend)).max(0.1).min(100.0);
                    predictions.push(params);
                }
            }
        }
        
        predictions.truncate(10);
        predictions
    }
    
    fn analyze_zoom_trend(&self, history: &VecDeque<ComputeParams>) -> f64 {
        if history.len() < 2 {
            return 0.0;
        }
        
        let recent: Vec<f64> = history
            .iter()
            .rev()
            .take(5)
            .map(|p| p.zoom)
            .collect();
        
        if recent.len() < 2 {
            return 0.0;
        }
        
        let mut sum_change = 0.0;
        for i in 1..recent.len() {
            sum_change += (recent[i - 1] / recent[i]).ln();
        }
        
        sum_change / (recent.len() - 1) as f64
    }
}

pub struct HierarchicalCache {
    l1_cache: Arc<Cache<String, Arc<Vec<DataPoint>>>>,
    l2_cache: Arc<Cache<String, Vec<u8>>>,
    l3_storage: Arc<tokio::sync::Mutex<Option<memmap2::MmapMut>>>,
}

impl HierarchicalCache {
    pub fn new() -> Self {
        let l1 = Cache::builder()
            .max_capacity(20)
            .time_to_live(Duration::from_secs(60))
            .build();
        
        let l2 = Cache::builder()
            .max_capacity(100)
            .time_to_live(Duration::from_secs(600))
            .build();
        
        Self {
            l1_cache: Arc::new(l1),
            l2_cache: Arc::new(l2),
            l3_storage: Arc::new(tokio::sync::Mutex::new(None)),
        }
    }
    
    pub async fn get(&self, key: &str) -> Option<Arc<Vec<DataPoint>>> {
        if let Some(data) = self.l1_cache.get(key) {
            return Some(data);
        }
        
        if let Some(compressed) = self.l2_cache.get(key) {
            if let Ok(decompressed) = self.decompress(&compressed) {
                let arc_data = Arc::new(decompressed);
                self.l1_cache.insert(key.to_string(), arc_data.clone());
                return Some(arc_data);
            }
        }
        
        None
    }
    
    pub async fn insert(&self, key: String, data: Vec<DataPoint>) {
        let arc_data = Arc::new(data.clone());
        self.l1_cache.insert(key.clone(), arc_data);
        
        if let Ok(compressed) = self.compress(&data) {
            self.l2_cache.insert(key, compressed);
        }
    }
    
    fn compress(&self, data: &[DataPoint]) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
        let serialized = bincode::serialize(data)?;
        Ok(zstd::encode_all(&serialized[..], 1)?)
    }
    
    fn decompress(&self, compressed: &[u8]) -> Result<Vec<DataPoint>, Box<dyn std::error::Error>> {
        let decompressed = zstd::decode_all(compressed)?;
        Ok(bincode::deserialize(&decompressed)?)
    }
    
    pub fn evict_to_l2(&self) {
        self.l1_cache.run_pending_tasks();
    }
}