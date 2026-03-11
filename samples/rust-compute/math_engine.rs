// Excerpt from math_engine.rs (1,030 lines total)
// Full source implements Lorenz, Mandelbrot, Julia, Logistic Map, and 3D surface visualizations

use nalgebra::{Vector3, Vector4};
use num_complex::Complex;
use rand::Rng;
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
// SIMD handled manually with platform-specific code
use std::sync::Arc;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DataPoint {
    pub x: f32,
    pub y: f32,
    pub z: f32,
    pub value: f32,
    pub iteration: u32,
    pub red: f32,
    pub green: f32,
    pub blue: f32,
    pub alpha: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComputeParams {
    pub visualization_type: String,
    pub points: usize,
    pub sigma: f64,
    pub rho: f64,
    pub beta: f64,
    pub zoom: f64,
    pub iterations: u32,
    pub x_offset: f64,
    pub y_offset: f64,
}

pub struct MathEngine {
    thread_pool: Arc<rayon::ThreadPool>,
    cpu_features: CpuFeatures,
}

#[derive(Debug, Clone)]
pub struct CpuFeatures {
    pub has_avx2: bool,
    pub has_avx512: bool,
    pub has_fma: bool,
}

impl CpuFeatures {
    #[cfg(target_arch = "x86_64")]
    pub fn detect() -> Self {
        use raw_cpuid::CpuId;
        let cpuid = CpuId::new();
        
        let has_avx2 = cpuid
            .get_extended_feature_info()
            .map_or(false, |info| info.has_avx2());
        
        let has_avx512 = cpuid
            .get_extended_feature_info()
            .map_or(false, |info| info.has_avx512f());
        
        let has_fma = cpuid
            .get_feature_info()
            .map_or(false, |info| info.has_fma());
        
        Self {
            has_avx2,
            has_avx512,
            has_fma,
        }
    }
    
    #[cfg(not(target_arch = "x86_64"))]
    pub fn detect() -> Self {
        Self {
            has_avx2: false,
            has_avx512: false,
            has_fma: false,
        }
    }
}

impl MathEngine {
    pub fn new() -> Self {
        let thread_pool = rayon::ThreadPoolBuilder::new()
            .num_threads(num_cpus::get())
            .build()
            .unwrap();
        
        Self {
            thread_pool: Arc::new(thread_pool),
            cpu_features: CpuFeatures::detect(),
        }
    }
    
    fn calculate_color(&self, x: f64, y: f64, z: f64, _value: f64, iteration: u32, _max_iter: u32, _viz_type: &str, sigma: f64, rho: f64, beta: f64) -> (f32, f32, f32, f32) {
        // Simple, safe Lorenz coloring that prevents stack overflow
        
        // Basic height-based coloring
        let z_norm = ((z + 10.0) / 40.0).clamp(0.0, 1.0);
        
        // Wing-based variation
        let x_norm = (x / 20.0).clamp(-1.0, 1.0);
        
        // Parameter influence
        let sigma_factor = (sigma / 10.0).clamp(0.5, 2.0);
        let rho_factor = (rho / 28.0).clamp(0.5, 2.0);
        let beta_factor = (beta / 2.67).clamp(0.5, 2.0);
        
        // Simple color mapping
        let hue_base = z_norm * 0.8;
        let hue_shift = x_norm * 0.1 + (sigma_factor - 1.0) * 0.1 + (rho_factor - 1.0) * 0.1;
        let final_hue = (hue_base + hue_shift).clamp(0.0, 1.0);
        
        // Convert to RGB using simple method
        let hue_deg = final_hue * 360.0;
        let (red, green, blue) = if hue_deg < 120.0 {
            let t = hue_deg / 120.0;
            (1.0 - t, t, 0.0)
        } else if hue_deg < 240.0 {
            let t = (hue_deg - 120.0) / 120.0;
            (0.0, 1.0 - t, t)
        } else {
            let t = (hue_deg - 240.0) / 120.0;
            (t, 0.0, 1.0 - t)
        };
        
        // Ensure good saturation and brightness
        let sat = 0.8;
        let brightness = 0.7;
        
        let final_red = (red * sat + (1.0 - sat)) * brightness;
        let final_green = (green * sat + (1.0 - sat)) * brightness;
        let final_blue = (blue * sat + (1.0 - sat)) * brightness;
        
        (final_red as f32, final_green as f32, final_blue as f32, 0.7)
    }
    
    // Simple color function for unused visualizations
    fn calculate_color_old(&self, x: f64, y: f64, z: f64, value: f64, _iteration: u32, _max_iter: u32, _viz_type: &str) -> (f32, f32, f32, f32) {
        (value as f32, 0.5, 1.0 - value as f32, 0.6)
    }
    
    fn hsl_to_rgb(h: f64, s: f64, l: f64) -> (f32, f32, f32) {
        let h = h / 360.0;
        let c = (1.0 - (2.0 * l - 1.0).abs()) * s;
        let x = c * (1.0 - ((h * 6.0) % 2.0 - 1.0).abs());
        let m = l - c / 2.0;
        
        let (r_prime, g_prime, b_prime) = match (h * 6.0) as i32 {
            0 => (c, x, 0.0),
            1 => (x, c, 0.0),
            2 => (0.0, c, x),
            3 => (0.0, x, c),
            4 => (x, 0.0, c),
            _ => (c, 0.0, x),
        };
        
        ((r_prime + m) as f32, (g_prime + m) as f32, (b_prime + m) as f32)
    }
    
    pub fn compute(&self, params: &ComputeParams) -> Vec<DataPoint> {
        self.compute_lorenz(params)
    }
    
    pub fn compute_lorenz(&self, params: &ComputeParams) -> Vec<DataPoint> {
        let sigma = params.sigma;
        let rho = params.rho;
        let beta = params.beta;
        let dt = 0.003; // Smaller timestep for better accuracy
        let points_per_trajectory = (params.points as f64).sqrt() as usize;
        let num_trajectories = params.points / points_per_trajectory;
        let skip_transient = 1000; // Skip initial transient behavior
        
        self.thread_pool.install(|| {
            (0..num_trajectories)
                .into_par_iter()
                .flat_map(|i| {
                    let mut rng = rand::thread_rng();
                    // Better initial conditions near the attractor
                    let mut x = rng.gen_range(-15.0..15.0);
                    let mut y = rng.gen_range(-20.0..20.0);
                    let mut z = rng.gen_range(5.0..45.0);
                    
                    // Skip transient behavior
                    for _ in 0..skip_transient {
                        let dx = sigma * (y - x) * dt;
                        let dy = (x * (rho - z) - y) * dt;
                        let dz = (x * y - beta * z) * dt;
                        x += dx;
                        y += dy;
                        z += dz;
                    }
                    
                    (0..points_per_trajectory)
                        .map(|j| {
                            // Runge-Kutta 4th order integration for better accuracy
                            let k1x = sigma * (y - x);
                            let k1y = x * (rho - z) - y;
                            let k1z = x * y - beta * z;
                            
                            let k2x = sigma * ((y + dt * k1y / 2.0) - (x + dt * k1x / 2.0));
                            let k2y = (x + dt * k1x / 2.0) * (rho - (z + dt * k1z / 2.0)) - (y + dt * k1y / 2.0);
                            let k2z = (x + dt * k1x / 2.0) * (y + dt * k1y / 2.0) - beta * (z + dt * k1z / 2.0);
                            
                            let k3x = sigma * ((y + dt * k2y / 2.0) - (x + dt * k2x / 2.0));
                            let k3y = (x + dt * k2x / 2.0) * (rho - (z + dt * k2z / 2.0)) - (y + dt * k2y / 2.0);
                            let k3z = (x + dt * k2x / 2.0) * (y + dt * k2y / 2.0) - beta * (z + dt * k2z / 2.0);
                            
                            let k4x = sigma * ((y + dt * k3y) - (x + dt * k3x));
                            let k4y = (x + dt * k3x) * (rho - (z + dt * k3z)) - (y + dt * k3y);
                            let k4z = (x + dt * k3x) * (y + dt * k3y) - beta * (z + dt * k3z);
                            
                            x += dt * (k1x + 2.0 * k2x + 2.0 * k3x + k4x) / 6.0;
                            y += dt * (k1y + 2.0 * k2y + 2.0 * k3y + k4y) / 6.0;
                            z += dt * (k1z + 2.0 * k2z + 2.0 * k3z + k4z) / 6.0;
                            
                            let distance_from_origin = (x * x + y * y + z * z).sqrt();
                            
                            let value = (distance_from_origin / 50.0).min(1.0);
                            let (r, g, b, a) = self.calculate_color(x, y, z, value, (i * points_per_trajectory + j) as u32, points_per_trajectory as u32, "lorenz", sigma, rho, beta);
                            
                            DataPoint {
                                x: (x * params.zoom + params.x_offset) as f32,
                                y: (y * params.zoom + params.y_offset) as f32,
                                z: z as f32,
                                value: value as f32,
                                iteration: (i * points_per_trajectory + j) as u32,
                                red: r,
                                green: g,
                                blue: b,
                                alpha: a,
                            }
                        })
                        .collect::<Vec<_>>()
                })
                .collect()
        })
    }
