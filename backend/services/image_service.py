"""
Image Service - Desktop Automation için image işlemleri
--------------------------------------------------------
Base64 encoding/decoding, resizing, optimization, compression
"""

from PIL import Image
from io import BytesIO
import base64
import gzip
import json
from typing import Optional, Dict, Any, Tuple
from datetime import datetime


class ImageService:
    """Image processing servisi"""
    
    @staticmethod
    def encode_image_to_base64(
        image_data: bytes,
        max_width: int = 800,
        format: str = "PNG"
    ) -> Dict[str, Any]:
        """
        Image'ı base64'e encode et ve optimize et.
        
        Args:
            image_data: Raw image bytes
            max_width: Maksimum genişlik (aspect ratio korunur)
            format: Çıktı formatı (PNG, JPEG)
        
        Returns:
            {
                "data": "base64_string",
                "format": "png",
                "width": 600,
                "height": 400,
                "original_width": 1920,
                "original_height": 1080,
                "size_kb": 45.2,
                "captured_at": "2024-01-15T10:30:00"
            }
        """
        try:
            # Image'ı aç
            img = Image.open(BytesIO(image_data))
            original_width, original_height = img.size
            
            # RGBA -> RGB dönüşümü (PNG için)
            if img.mode == 'RGBA':
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                rgb_img.paste(img, mask=img.split()[3])
                img = rgb_img
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Resize (aspect ratio koru)
            if img.width > max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
            
            # Optimize ve encode
            buffered = BytesIO()
            save_format = format.upper()
            
            if save_format == "PNG":
                img.save(buffered, format="PNG", optimize=True)
            elif save_format == "JPEG":
                img.save(buffered, format="JPEG", quality=85, optimize=True)
            else:
                img.save(buffered, format="PNG", optimize=True)
            
            # Base64 encode
            img_bytes = buffered.getvalue()
            base64_str = base64.b64encode(img_bytes).decode('utf-8')
            
            return {
                "data": base64_str,
                "format": save_format.lower(),
                "width": img.width,
                "height": img.height,
                "original_width": original_width,
                "original_height": original_height,
                "size_kb": round(len(img_bytes) / 1024, 2),
                "captured_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            raise ValueError(f"Image encoding error: {str(e)}")
    
    @staticmethod
    def decode_base64_to_image(
        base64_str: str,
        save_path: Optional[str] = None
    ) -> Image.Image:
        """
        Base64 string'i Image'a decode et.
        
        Args:
            base64_str: Base64 encoded image
            save_path: Opsiyonel kayıt yolu
        
        Returns:
            PIL Image object
        """
        try:
            img_bytes = base64.b64decode(base64_str)
            img = Image.open(BytesIO(img_bytes))
            
            if save_path:
                img.save(save_path)
            
            return img
            
        except Exception as e:
            raise ValueError(f"Image decoding error: {str(e)}")
    
    @staticmethod
    def create_thumbnail(
        base64_str: str,
        size: Tuple[int, int] = (150, 150)
    ) -> str:
        """
        Thumbnail oluştur.
        
        Args:
            base64_str: Base64 encoded image
            size: Thumbnail boyutu (width, height)
        
        Returns:
            Base64 encoded thumbnail
        """
        try:
            img_bytes = base64.b64decode(base64_str)
            img = Image.open(BytesIO(img_bytes))
            
            img.thumbnail(size, Image.Resampling.LANCZOS)
            
            buffered = BytesIO()
            img.save(buffered, format="JPEG", quality=70)
            
            return base64.b64encode(buffered.getvalue()).decode('utf-8')
            
        except Exception as e:
            raise ValueError(f"Thumbnail creation error: {str(e)}")
    
    @staticmethod
    def compress_scenario_json(scenario_data: dict) -> bytes:
        """
        Scenario JSON'u gzip ile sıkıştır.
        
        Args:
            scenario_data: Scenario dict
        
        Returns:
            Gzip compressed bytes
        """
        json_str = json.dumps(scenario_data, ensure_ascii=False)
        return gzip.compress(json_str.encode('utf-8'))
    
    @staticmethod
    def decompress_scenario_json(compressed_data: bytes) -> dict:
        """
        Gzip compressed scenario JSON'u aç.
        
        Args:
            compressed_data: Gzip compressed bytes
        
        Returns:
            Scenario dict
        """
        json_str = gzip.decompress(compressed_data).decode('utf-8')
        return json.loads(json_str)
    
    @staticmethod
    def calculate_scenario_size(scenario_data: dict) -> Dict[str, Any]:
        """
        Scenario dosya boyutunu hesapla.
        
        Args:
            scenario_data: Scenario dict
        
        Returns:
            {
                "total_images": 5,
                "total_size_kb": 450.2,
                "json_size_kb": 500.5,
                "average_image_size_kb": 90.0
            }
        """
        steps = scenario_data.get("steps", [])
        total_size = 0
        image_count = 0
        
        for step in steps:
            image_data = step.get("image")
            if image_data and isinstance(image_data, dict):
                size_kb = image_data.get("size_kb", 0)
                total_size += size_kb
                image_count += 1
        
        json_str = json.dumps(scenario_data, ensure_ascii=False)
        json_size_kb = len(json_str.encode('utf-8')) / 1024
        
        avg_size = round(total_size / image_count, 2) if image_count > 0 else 0
        
        return {
            "total_images": image_count,
            "total_size_kb": round(total_size, 2),
            "json_size_kb": round(json_size_kb, 2),
            "average_image_size_kb": avg_size
        }
    
    @staticmethod
    def extract_images_from_scenario(
        scenario_data: dict,
        output_dir: str
    ) -> int:
        """
        Scenario içindeki tüm image'ları dışarı çıkar (debug/inspection için).
        
        Args:
            scenario_data: Scenario dict
            output_dir: Çıktı klasörü
        
        Returns:
            Çıkarılan image sayısı
        """
        import os
        os.makedirs(output_dir, exist_ok=True)
        
        count = 0
        steps = scenario_data.get("steps", [])
        
        for i, step in enumerate(steps):
            image_data = step.get("image")
            if image_data and isinstance(image_data, dict):
                base64_str = image_data.get("data")
                image_name = image_data.get("name", f"step_{i+1}.png")
                
                if base64_str:
                    filepath = os.path.join(output_dir, image_name)
                    ImageService.decode_base64_to_image(base64_str, filepath)
                    count += 1
        
        return count


image_service = ImageService()