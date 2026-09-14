from PIL import Image
import imagehash

def get_image_hash(image_path: str):
    """
    Tính toán perceptual hash của ảnh sử dụng dHash hoặc pHash.
    """
    try:
        img = Image.open(image_path)
        # Sử dụng phash vì nó kháng nén và thay đổi kích thước tốt
        return imagehash.phash(img)
    except Exception as e:
        print(f"Lỗi khi xử lý ảnh {image_path}: {e}")
        return None

def compare_hashes(hash1, hash2):
    """
    So sánh 2 hash và trả về độ tương đồng (%).
    """
    if hash1 is None or hash2 is None:
        return 0.0
        
    # Kích thước hash mặc định là 8x8 = 64 bit
    max_diff = 64.0
    
    # Phép trừ giữa 2 hash trả về khoảng cách Hamming (số bit khác nhau)
    diff = hash1 - hash2
    
    similarity = (1.0 - (diff / max_diff)) * 100
    return similarity

