use crate::math_engine::{ComputeParams, DataPoint, MathEngine};
use crate::memory_pool::MemoryPool;
use crossbeam::channel::{bounded, Receiver, Sender};
use dashmap::DashMap;
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};
use tokio::sync::mpsc;

pub struct ComputeRequest {
    pub id: String,
    pub params: ComputeParams,
    pub priority: u8,
}

pub struct ComputeResult {
    pub id: String,
    pub data: Arc<Vec<DataPoint>>,
    pub compute_time_ms: u64,
    pub compressed_size: usize,
}

pub struct ComputationPipeline {
    input_queue: Sender<ComputeRequest>,
    input_receiver: Receiver<ComputeRequest>,
    output_stream: mpsc::UnboundedSender<ComputeResult>,
    cache_layer: Arc<DashMap<String, Arc<Vec<DataPoint>>>>,
    thread_pool: Arc<rayon::ThreadPool>,
    math_engine: Arc<MathEngine>,
    memory_pool: Arc<tokio::sync::Mutex<MemoryPool>>,
}

impl ComputationPipeline {
    pub fn new(output_stream: mpsc::UnboundedSender<ComputeResult>) -> Self {
        let (input_queue, input_receiver) = bounded(1000);
        
        let thread_pool = rayon::ThreadPoolBuilder::new()
            .num_threads(num_cpus::get())
            .thread_name(|i| format!("compute-{}", i))
            .build()
            .unwrap();
        
        Self {
            input_queue,
            input_receiver,
            output_stream,
            cache_layer: Arc::new(DashMap::new()),
            thread_pool: Arc::new(thread_pool),
            math_engine: Arc::new(MathEngine::new()),
            memory_pool: Arc::new(tokio::sync::Mutex::new(MemoryPool::new())),
        }
    }
    
    pub fn submit_request(&self, request: ComputeRequest) -> Result<(), String> {
        self.input_queue
            .send(request)
            .map_err(|e| format!("Failed to submit request: {}", e))
    }
    
    pub async fn start_processing(self: Arc<Self>) {
        let pipeline = self.clone();
        
        thread::spawn(move || {
            while let Ok(request) = pipeline.input_receiver.recv() {
                let pipeline_clone = pipeline.clone();
                let start_time = Instant::now();
                
                pipeline.thread_pool.spawn(move || {
                    let cache_key = format!(
                        "{}_{}_{}_{}_{}_{}",
                        request.params.visualization_type,
                        request.params.points,
                        request.params.sigma,
                        request.params.rho,
                        request.params.beta,
                        request.params.iterations
                    );
                    
                    let data = if let Some(cached) = pipeline_clone.cache_layer.get(&cache_key) {
                        cached.clone()
                    } else {
                        let computed = pipeline_clone.math_engine.compute(&request.params);
                        let arc_data = Arc::new(computed);
                        pipeline_clone.cache_layer.insert(cache_key.clone(), arc_data.clone());
                        arc_data
                    };
                    
                    let compute_time_ms = start_time.elapsed().as_millis() as u64;
                    
                    let compressed_size = data.len() * std::mem::size_of::<DataPoint>() / 10;
                    
                    let result = ComputeResult {
                        id: request.id,
                        data,
                        compute_time_ms,
                        compressed_size,
                    };
                    
                    let _ = pipeline_clone.output_stream.send(result);
                });
            }
        });
    }
    
    pub fn get_cache_stats(&self) -> CacheStats {
        CacheStats {
            total_entries: self.cache_layer.len(),
            total_size_bytes: self.cache_layer
                .iter()
                .map(|entry| entry.value().len() * std::mem::size_of::<DataPoint>())
                .sum(),
        }
    }
    
    pub fn clear_cache(&self) {
        self.cache_layer.clear();
    }
    
    pub async fn prefetch_common_parameters(&self) {
        let common_params = vec![
            ("lorenz", 500000, 10.0, 28.0, 8.0/3.0, 1.0, 1000),
            ("mandelbrot", 1000000, 10.0, 28.0, 8.0/3.0, 1.0, 256),
            ("julia", 1000000, 10.0, 28.0, 8.0/3.0, 1.0, 256),
            ("clifford", 500000, 10.0, 28.0, 8.0/3.0, 1.0, 1000),
        ];
        
        for (viz_type, points, sigma, rho, beta, zoom, iterations) in common_params {
            let params = ComputeParams {
                visualization_type: viz_type.to_string(),
                points,
                sigma,
                rho,
                beta,
                zoom,
                iterations,
                x_offset: 0.0,
                y_offset: 0.0,
            };
            
            let request = ComputeRequest {
                id: format!("prefetch_{}", viz_type),
                params,
                priority: 0,
            };
            
            let _ = self.submit_request(request);
        }
    }
}

pub struct CacheStats {
    pub total_entries: usize,
    pub total_size_bytes: usize,
}

pub struct StreamingCompressor;

impl StreamingCompressor {
    pub fn new() -> Self {
        Self
    }
    
    pub fn compress_points(&self, points: &[DataPoint]) -> Vec<u8> {
        let serialized = bincode::serialize(points).unwrap();
        
        let mut encoder = lz4::EncoderBuilder::new()
            .level(1)
            .build(Vec::with_capacity(serialized.len() / 2))
            .unwrap();
        
        use std::io::Write;
        encoder.write_all(&serialized).unwrap();
        let (compressed, _) = encoder.finish();
        compressed
    }
    
    pub fn create_binary_frame(points: &[DataPoint]) -> Vec<u8> {
        let mut buffer = Vec::with_capacity(points.len() * 16);
        
        buffer.extend_from_slice(&(points.len() as u32).to_le_bytes());
        
        for point in points {
            buffer.extend_from_slice(&point.x.to_le_bytes());
            buffer.extend_from_slice(&point.y.to_le_bytes());
            buffer.extend_from_slice(&point.z.to_le_bytes());
            buffer.extend_from_slice(&point.value.to_le_bytes());
        }
        
        buffer
    }
}

pub struct AdaptiveScheduler {
    performance_history: Vec<(String, Duration)>,
    optimization_threshold: Duration,
}

impl AdaptiveScheduler {
    pub fn new() -> Self {
        Self {
            performance_history: Vec::with_capacity(100),
            optimization_threshold: Duration::from_millis(100),
        }
    }
    
    pub fn record_performance(&mut self, visualization_type: String, duration: Duration) {
        self.performance_history.push((visualization_type, duration));
        
        if self.performance_history.len() > 100 {
            self.performance_history.remove(0);
        }
    }
    
    pub fn should_optimize(&self, visualization_type: &str) -> bool {
        self.performance_history
            .iter()
            .filter(|(vt, _)| vt == visualization_type)
            .take(5)
            .any(|(_, duration)| *duration > self.optimization_threshold)
    }
    
    pub fn get_average_performance(&self, visualization_type: &str) -> Option<Duration> {
        let relevant: Vec<Duration> = self.performance_history
            .iter()
            .filter(|(vt, _)| vt == visualization_type)
            .map(|(_, d)| *d)
            .collect();
        
        if relevant.is_empty() {
            None
        } else {
            let sum: Duration = relevant.iter().sum();
            Some(sum / relevant.len() as u32)
        }
    }
}